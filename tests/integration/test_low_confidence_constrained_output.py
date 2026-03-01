from core.config import load_config
from core.models import RetrievedDoc
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _doc(provider: str, title: str, url: str, snippet: str, tier: str = "C") -> RetrievedDoc:
    return RetrievedDoc(
        provider=provider,  # type: ignore[arg-type]
        title=title,
        url=url,
        snippet=snippet,
        content=snippet,
        score=0.56,
        meta={"source_tier": tier, "confidence": "low" if tier == "C" else "medium"},
    )


def test_constrained_actionable_output_when_evidence_is_weak(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "truth_mode": "balanced",
            "insufficient_evidence_output": "constrained_actionable",
            "claim_policy": "adaptive_scoring",
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    def call_web_tool(tool_name: str, *args, **kwargs):
        del args, kwargs
        if tool_name == "tavily_search":
            return [
                _doc(
                    "tavily",
                    "Opinion blog",
                    "https://exampleblog.dev/post-1",
                    "This source claims a relationship but offers limited methodology.",
                ),
                _doc(
                    "tavily",
                    "Another opinion post",
                    "https://opinion-hub.dev/article",
                    "Arguments are interpretive and not strongly corroborated.",
                ),
            ]
        if tool_name == "ddg_search":
            return [
                _doc(
                    "ddg",
                    "General commentary",
                    "https://commentary-site.dev/analysis",
                    "Discussion exists, but evidence quality appears mixed and uncertain.",
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

    state = run_graph("Explain the relationship of islam and quantum physics", runtime)
    report = state.get("final_report", "")
    assert "### Directional / Constrained Findings" in report
    assert "### Withheld Claims" in report
    assert "Next retrieval step" in report or "directional" in report.lower()
