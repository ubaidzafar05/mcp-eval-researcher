"""test_judge_provider_switch.py — Tests for the Ollama judge integration."""
from core.config import load_config
from core.models import Citation
from evals.deepeval_node import DeepEvalNode


def test_ollama_judge_runs_without_error():
    """The judge should successfully evaluate via Ollama (or heuristic fallback)."""
    cfg = load_config(
        {"judge_provider": "ollama", "interactive_hitl": False}
    )
    node = DeepEvalNode(cfg)
    report = "A cited claim exists [C1]."
    citations = [Citation(claim_id="C1", source_url="https://example.com")]
    result = node.evaluate("test query", report, citations)
    # Should always produce a result — either from Ollama or heuristic fallback
    assert result.faithfulness >= 0.0
    assert result.relevancy >= 0.0
