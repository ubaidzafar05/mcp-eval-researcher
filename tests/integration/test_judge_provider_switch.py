from core.config import load_config
from core.models import Citation
from evals.deepeval_node import DeepEvalNode


def test_hf_judge_falls_back_without_token():
    cfg = load_config(
        {"judge_provider": "hf", "hf_token": None, "interactive_hitl": False}
    )
    node = DeepEvalNode(cfg)
    report = "A cited claim exists [C1]."
    citations = [Citation(claim_id="C1", source_url="https://example.com")]
    result = node.evaluate("test query", report, citations)
    assert result.reasons
    assert any("HF token missing" in reason for reason in result.reasons)

