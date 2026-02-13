from __future__ import annotations

import json
from typing import Any

import httpx

from core.models import Citation, EvalResult, RunConfig


def _heuristic_score(query: str, report: str, citation_coverage: float) -> EvalResult:
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
        reasons=[],
    )


def judge_with_groq(
    query: str,
    report: str,
    citations: list[Citation],
    citation_coverage: float,
    config: RunConfig,
) -> EvalResult:
    base = _heuristic_score(query, report, citation_coverage)
    if not config.groq_api_key:
        return base

    prompt = {
        "query": query,
        "report": report[:9000],
        "citation_coverage": citation_coverage,
        "task": (
            "Score faithfulness and relevancy between 0 and 1. "
            "Return JSON: {faithfulness: float, relevancy: float, reasons: [str,...]}"
        ),
    }
    body = {
        "model": config.groq_model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "You are a strict evaluator. Output JSON only."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
    }
    headers = {
        "Authorization": f"Bearer {config.groq_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=18.0) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
        data: dict[str, Any] = json.loads(content)
        faithfulness = float(data.get("faithfulness", base.faithfulness))
        relevancy = float(data.get("relevancy", base.relevancy))
        reasons = [str(r) for r in data.get("reasons", [])]
        return EvalResult(
            faithfulness=max(0.0, min(1.0, faithfulness)),
            relevancy=max(0.0, min(1.0, relevancy)),
            citation_coverage=base.citation_coverage,
            pass_gate=False,
            reasons=reasons,
        )
    except Exception:  # noqa: BLE001
        return base

