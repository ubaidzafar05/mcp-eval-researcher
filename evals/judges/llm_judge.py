from __future__ import annotations

import json
from typing import Any

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

def judge_with_llm(
    query: str,
    report: str,
    citations: list[Citation],
    citation_coverage: float,
    config: RunConfig,
    client: Any,
    provider: str,
    model: str,
) -> EvalResult:
    base = _heuristic_score(query, report, citation_coverage)
    
    prompt = {
        "query": query,
        "report": report[:9000],
        "citation_coverage": citation_coverage,
        "task": (
            "Score faithfulness and relevancy between 0 and 1. "
            "Return JSON: {faithfulness: float, relevancy: float, reasons: [str,...]}"
        ),
    }
    
    system_msg = "You are a strict evaluator. Output JSON only."
    user_msg = json.dumps(prompt)
    
    try:
        content = ""
        if provider == "openai" or provider == "groq":
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1
            )
            content = resp.choices[0].message.content
        elif provider == "anthropic":
            resp = client.messages.create(
                model=model,
                max_tokens=1000,
                system=system_msg,
                messages=[
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1
            )
            content = resp.content[0].text
            
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
    except Exception as e:
        print(f"Judge LLM failed: {e}")
        return base
