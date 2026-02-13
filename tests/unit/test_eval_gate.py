from core.config import load_config
from core.models import Citation
from evals.deepeval_node import DeepEvalNode


def test_eval_gate_threshold_logic():
    cfg = load_config(
        {
            "judge_provider": "groq",
            "faithfulness_threshold": 0.7,
            "relevancy_threshold": 0.7,
            "citation_threshold": 0.85,
            "interactive_hitl": False,
        }
    )
    evaluator = DeepEvalNode(cfg)
    report = "Cloud Hive improves reliability with retries [C1]."
    citations = [Citation(claim_id="C1", source_url="https://example.com")]
    result = evaluator.evaluate("Cloud Hive reliability", report, citations)
    assert result.citation_coverage >= 0.85
    assert 0.0 <= result.faithfulness <= 1.0
    assert 0.0 <= result.relevancy <= 1.0

