from __future__ import annotations

from typing import Any

from core.citations import validate_claim_level_citations
from core.models import Citation, EvalResult, RunConfig
from evals.judges.llm_judge import judge_with_llm
from evals.judges.stub_judge import judge_with_stub
from agents.model_router import ModelRouter


class DeepEvalNode:
    def __init__(self, config: RunConfig, runtime: Any = None):
        self.config = config
        self.runtime = runtime

    def evaluate(self, query: str, report: str, citations: list[Citation]) -> EvalResult:
        citation_ok, citation_reasons, coverage = validate_claim_level_citations(
            report, citations, min_coverage=self.config.citation_threshold
        )
        
        # Determine judge
        if self.config.judge_provider == "stub":
            result = judge_with_stub(query, report, citations, coverage)
        elif self.runtime and self.runtime.model_router:
            # Use router
            router: ModelRouter = self.runtime.model_router
            model_selection = router.select_model(
                task_type="evaluation",
                context_size=len(report),
                latency_budget_ms=2000,
                tenant_tier="default" # Could come from state if passed
            )
            try:
                client = self.runtime.get_llm_client(model_selection.provider)
                result = judge_with_llm(
                    query, report, citations, coverage, self.config, client, 
                    model_selection.provider, model_selection.model_name
                )
            except Exception:
                # Fallback
                result = judge_with_stub(query, report, citations, coverage)
        else:
            # Fallback
            result = judge_with_stub(query, report, citations, coverage)

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
