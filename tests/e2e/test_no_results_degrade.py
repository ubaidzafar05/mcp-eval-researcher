from core.config import load_config
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def test_no_results_degrades_gracefully(monkeypatch, tmp_path):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "memory_dir": str(tmp_path / "memory"),
            "output_dir": str(tmp_path / "outputs"),
            "logs_dir": str(tmp_path / "logs"),
            "data_dir": str(tmp_path / "data"),
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    monkeypatch.setattr(runtime.memory_store, "retrieve_similar", lambda query, k=3: [])

    monkeypatch.setattr(runtime.mcp_client.web_server, "tavily_search", lambda q, k=5: [])
    monkeypatch.setattr(runtime.mcp_client.web_server, "ddg_search", lambda q, k=5: [])
    monkeypatch.setattr(
        runtime.mcp_client.web_server, "firecrawl_extract", lambda q, mode="extract": []
    )
    state = run_graph("obscure unknown topic", runtime)
    report = state.get("final_report", "")
    assert "Insufficient source context" in report or "No reliable external sources" in report
