from core.config import load_config
from core.models import Citation
from evals.deepeval_node import DeepEvalNode


def test_eval_gate_threshold_logic():
    cfg = load_config(
        {
            "judge_provider": "stub",
            "faithfulness_threshold": 0.7,
            "relevancy_threshold": 0.7,
            "citation_threshold": 0.85,
            "source_policy": "external_only",
            "research_depth": "balanced",
            "min_external_sources": 1,
            "min_unique_providers": 1,
            "interactive_hitl": False,
        }
    )
    evaluator = DeepEvalNode(cfg)
    report = """
## Executive Summary
Short synthesis [C1].

## Scope and Method
- Baseline method.

## Evidence Matrix
- [C1] Evidence row.

## Key Findings
- [C1] Cloud Hive improves reliability with retries.

## Counterevidence / Alternative Interpretations
- Limited scope caveat.

## Risks, Gaps, and Uncertainty
- Narrow evidence base.

## Recommendations
- Expand sample size.

## Sources Used
- [C1] Example (tavily) - https://example.com
"""
    citations = [Citation(claim_id="C1", source_url="https://example.com", provider="tavily")]
    result = evaluator.evaluate("Cloud Hive reliability", report, citations)
    assert result.citation_coverage >= 0.85
    assert 0.0 <= result.faithfulness <= 1.0
    assert 0.0 <= result.relevancy <= 1.0
    if not result.pass_gate:
        assert result.reasons
