from __future__ import annotations

import json
from typing import Any

import httpx

from core.models import Citation, EvalResult, RunConfig
from evals.judges.groq_judge import _heuristic_score


def judge_with_hf(
    query: str,
    report: str,
    citations: list[Citation],
    citation_coverage: float,
    config: RunConfig,
) -> EvalResult:
    base = _heuristic_score(query, report, citation_coverage)
    if not config.hf_token:
        base.reasons.append("HF token missing; heuristic fallback was used.")
        return base

    # This adapter expects an instruct/chat model endpoint on HF Inference.
    model = "mistralai/Mistral-7B-Instruct-v0.3"
    prompt = (
        "Return strict JSON only with keys faithfulness,relevancy,reasons.\n"
        f"Query: {query}\nReport: {report[:8000]}\n"
        f"Citation coverage: {citation_coverage}\n"
    )
    headers = {"Authorization": f"Bearer {config.hf_token}"}
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 200, "temperature": 0.1}}
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data: Any = resp.json()

        generated = ""
        if isinstance(data, list) and data:
            generated = str(data[0].get("generated_text", ""))
        elif isinstance(data, dict):
            generated = str(data.get("generated_text", ""))
        scores = json.loads(generated)
        return EvalResult(
            faithfulness=max(0.0, min(1.0, float(scores.get("faithfulness", base.faithfulness)))),
            relevancy=max(0.0, min(1.0, float(scores.get("relevancy", base.relevancy)))),
            citation_coverage=base.citation_coverage,
            pass_gate=False,
            reasons=[str(x) for x in scores.get("reasons", [])],
        )
    except Exception:  # noqa: BLE001
        base.reasons.append("HF judge request failed; heuristic fallback was used.")
        return base

