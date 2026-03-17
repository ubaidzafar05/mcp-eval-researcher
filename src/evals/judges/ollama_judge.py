"""ollama_judge.py — Local Ollama judge for report evaluation.

Directly calls the Ollama ``/api/generate`` endpoint to score
faithfulness, relevancy, and citation coverage of research reports.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from core.models import Citation, EvalResult, RunConfig


def _heuristic_score(query: str, report: str, citation_coverage: float) -> EvalResult:
    """Deterministic fallback when the LLM judge is unavailable."""
    q_tokens = {t for t in query.lower().split() if len(t) > 2}
    r_tokens = {t for t in report.lower().split() if len(t) > 2}
    overlap = len(q_tokens & r_tokens) / max(1, len(q_tokens))
    faithfulness = min(1.0, 0.45 + citation_coverage * 0.55)
    relevancy = min(1.0, 0.35 + overlap * 0.65)
    return EvalResult(
        faithfulness=round(faithfulness, 3),
        relevancy=round(relevancy, 3),
        citation_coverage=round(citation_coverage, 3),
        pass_gate=False,
        reasons=["Heuristic judge score was used."],
        meta={"judge_fallback_used": True, "judge_fallback_reason": "heuristic_mode"},
    )


def judge_with_ollama(
    query: str,
    report: str,
    citations: list[Citation],
    citation_coverage: float,
    config: RunConfig,
) -> EvalResult:
    """Evaluate report quality using the local Ollama model."""
    del citations  # used only for type signature compatibility

    base = _heuristic_score(query, report, citation_coverage)
    if not config.ollama_endpoint:
        base.reasons.append("Ollama endpoint not configured; heuristic fallback was used.")
        return base

    model = config.ollama_model
    prompt = (
        "You are a strict evaluator. Return strict JSON only with keys: faithfulness, relevancy, reasons.\n"
        "faithfulness: How well the report is supported by the sources (0-1).\n"
        "relevancy: How well the report answers the query (0-1).\n"
        "reasons: List of specific observations about the report quality.\n\n"
        f"Query: {query}\n\n"
        f"Report: {report[:8000]}\n\n"
        f"Citation coverage: {citation_coverage}\n\n"
        "Respond with JSON only."
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 300,
        },
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{config.ollama_endpoint}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        generated = data.get("response", "").strip()
        json_start = generated.find("{")
        json_end = generated.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = generated[json_start:json_end]
            scores: dict[str, Any] = json.loads(json_str)
        else:
            scores = {}

        faithfulness = max(
            0.0,
            min(1.0, float(scores.get("faithfulness", base.faithfulness))),
        )
        relevancy = max(
            0.0,
            min(1.0, float(scores.get("relevancy", base.relevancy))),
        )
        reasons = [str(x) for x in scores.get("reasons", [])]
        return EvalResult(
            faithfulness=faithfulness,
            relevancy=relevancy,
            citation_coverage=base.citation_coverage,
            pass_gate=False,
            reasons=reasons,
            meta={"judge_fallback_used": False, "judge_provider": "ollama"},
        )
    except Exception as exc:  # noqa: BLE001
        base.reasons.append(f"Ollama judge request failed: {exc}; heuristic fallback was used.")
        return base
