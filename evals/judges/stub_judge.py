from __future__ import annotations

from core.models import Citation, EvalResult


def judge_with_stub(
    query: str,
    report: str,
    citations: list[Citation],
    citation_coverage: float,
) -> EvalResult:
    q_tokens = {t for t in query.lower().split() if len(t) > 2}
    r_tokens = {t for t in report.lower().split() if len(t) > 2}
    overlap = len(q_tokens & r_tokens) / max(1, len(q_tokens))

    faithfulness = round(min(1.0, 0.35 + citation_coverage * 0.55), 3)
    relevancy = round(min(1.0, 0.25 + overlap * 0.65), 3)
    reasons = ["Deterministic stub judge used for test stability."]
    return EvalResult(
        faithfulness=faithfulness,
        relevancy=relevancy,
        citation_coverage=round(citation_coverage, 3),
        pass_gate=False,
        reasons=reasons,
    )

