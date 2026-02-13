from core.config import load_config
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def test_graph_completes_happy_path():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    state = run_graph("What is LangGraph orchestration?", runtime)
    assert state.get("final_report")
    assert state.get("status") in {"completed", "completed_low_confidence"}


def test_graph_enters_low_confidence_after_retry_limit():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "faithfulness_threshold": 0.99,
            "relevancy_threshold": 0.99,
            "citation_threshold": 0.99,
            "correction_loop_limit": 1,
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    state = run_graph("niche ambiguous query with weak context", runtime)
    assert state.get("correction_count", 0) >= 1
    assert state.get("low_confidence") is True
