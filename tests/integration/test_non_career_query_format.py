from core.config import load_config
from core.models import RetrievedDoc
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _doc(provider: str, idx: int, url: str, snippet: str) -> RetrievedDoc:
    return RetrievedDoc(
        provider=provider,  # type: ignore[arg-type]
        title=f"{provider} source {idx}",
        url=url,
        snippet=snippet,
        content=snippet,
        score=0.8,
    )


def test_non_career_query_uses_domain_agnostic_structure(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "research_depth": "deep",
            "source_policy": "external_only",
            "dual_use_depth": "dynamic_defensive",
            "source_quality_bar": "high_confidence",
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    def call_web_tool(tool_name: str, *args, **kwargs):
        del args, kwargs
        if tool_name == "tavily_search":
            return [
                _doc(
                    "tavily",
                    1,
                    "https://arxiv.org/abs/2501.00001",
                    "AI detection techniques in blogs include stylometric and perplexity features.",
                ),
                _doc(
                    "tavily",
                    2,
                    "https://ieeexplore.ieee.org/document/123456",
                    "Defensive controls reduce false positives and evasion risk in moderation systems.",
                ),
            ]
        if tool_name == "ddg_search":
            return [
                _doc(
                    "ddg",
                    1,
                    "https://reuters.com/technology/example",
                    "Industry teams are deploying multi-signal detectors with human review safeguards.",
                )
            ]
        return []

    monkeypatch.setattr(runtime.mcp_client, "call_web_tool", call_web_tool)
    monkeypatch.setattr(runtime.memory_store, "retrieve_similar", lambda query, k=3: [])
    monkeypatch.setattr(
        GraphRuntime,
        "get_llm_client",
        lambda self, _provider: (_ for _ in ()).throw(Exception("offline")),
    )

    state = run_graph("can you tell me more about ai detection and bypassing in blogs", runtime)
    report = state.get("final_report", "")

    assert "## Executive Summary" in report
    assert "## Direct Answer" in report
    assert "## Verified Findings Register" in report
    assert "career outlook" not in report.lower()
    assert "ai engineer path" not in report.lower()
    assert "defensive" in report.lower()
