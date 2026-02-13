from core.config import load_config
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def test_provider_429_fallback(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    def fail_429(*args, **kwargs):
        raise RuntimeError("429 limit exceeded")

    monkeypatch.setattr(runtime.mcp_client.web_server, "tavily_search", fail_429)
    monkeypatch.setattr(runtime.mcp_client.web_server, "ddg_search", fail_429)
    state = run_graph("free tier retry strategy", runtime)
    assert state.get("final_report")
    assert state.get("status") in {"completed", "completed_low_confidence"}
