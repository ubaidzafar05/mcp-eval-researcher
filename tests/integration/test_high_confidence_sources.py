from core.config import load_config
from core.models import RetrievedDoc
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _doc(provider: str, title: str, url: str, snippet: str, score: float = 0.8) -> RetrievedDoc:
    return RetrievedDoc(
        provider=provider,  # type: ignore[arg-type]
        title=title,
        url=url,
        snippet=snippet,
        content=snippet,
        score=score,
    )


def test_high_confidence_mode_prioritizes_tier_ab(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "research_depth": "deep",
            "source_policy": "external_only",
            "source_quality_bar": "high_confidence",
            "min_tier_ab_sources": 2,
            "require_corroboration_for_tier_c": True,
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    def call_web_tool(tool_name: str, *args, **kwargs):
        del args, kwargs
        if tool_name == "tavily_search":
            return [
                _doc(
                    "tavily",
                    "AAAI paper",
                    "https://aaai.org/paper/example",
                    "Peer-reviewed evidence on detector robustness and feature engineering.",
                ),
                _doc(
                    "tavily",
                    "Random blog",
                    "https://some-random-blog.dev/post",
                    "Opinionated claims with limited methodology disclosure.",
                ),
            ]
        if tool_name == "ddg_search":
            return [
                _doc(
                    "ddg",
                    "Reuters analysis",
                    "https://reuters.com/technology/example",
                    "Independent coverage of deployment trends and governance practices.",
                ),
            ]
        return []

    monkeypatch.setattr(runtime.mcp_client, "call_web_tool", call_web_tool)
    monkeypatch.setattr(runtime.memory_store, "retrieve_similar", lambda query, k=3: [])
    monkeypatch.setattr(
        GraphRuntime,
        "get_llm_client",
        lambda self, _provider: (_ for _ in ()).throw(Exception("offline")),
    )

    state = run_graph("evaluate ai detection reliability in blog moderation", runtime)
    citations = state.get("citations", [])
    tiers = {(c.source_tier or "").upper() for c in citations}
    tier_ab_count = sum(1 for c in citations if (c.source_tier or "").upper() in {"A", "B"})

    assert "A" in tiers or "B" in tiers
    assert tier_ab_count >= 2
