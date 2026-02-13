from core.config import load_config
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def test_firecrawl_selective_trigger():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    state_without = run_graph("Compare LLM orchestration frameworks", runtime)
    assert state_without.get("firecrawl_requested") is False

    state_with = run_graph("Review https://example.com/docs API authentication", runtime)
    assert state_with.get("firecrawl_requested") is True
    assert "firecrawl_docs" in state_with
