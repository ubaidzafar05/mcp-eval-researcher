from __future__ import annotations

from core.citations import validate_claim_level_citations
from core.models import Citation, EvalResult, RunConfig
from evals.judges.groq_judge import judge_with_groq
from evals.judges.hf_judge import judge_with_hf
from evals.judges.stub_judge import judge_with_stub


class DeepEvalNode:
    def __init__(self, config: RunConfig):
        self.config = config

    def evaluate(self, query: str, report: str, citations: list[Citation]) -> EvalResult:
        citation_ok, citation_reasons, coverage = validate_claim_level_citations(
            report, citations, min_coverage=self.config.citation_threshold
        )
        if self.config.judge_provider == "stub":
            result = judge_with_stub(query, report, citations, coverage)
        elif self.config.judge_provider == "hf":
            result = judge_with_hf(query, report, citations, coverage, self.config)
        else:
            result = judge_with_groq(query, report, citations, coverage, self.config)

        reasons = list(result.reasons)
        if not citation_ok:
            reasons.extend(citation_reasons)
        pass_gate = (
            result.faithfulness >= self.config.faithfulness_threshold
            and result.relevancy >= self.config.relevancy_threshold
            and coverage >= self.config.citation_threshold
        )
        return EvalResult(
            faithfulness=result.faithfulness,
            relevancy=result.relevancy,
            citation_coverage=coverage,
            pass_gate=pass_gate,
            reasons=reasons,
        )
