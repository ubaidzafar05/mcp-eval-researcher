from core.config import load_config
from core.models import RetrievedDoc
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _doc(provider: str, title: str, url: str, snippet: str) -> RetrievedDoc:
    return RetrievedDoc(
        provider=provider,
        title=title,
        url=url,
        snippet=snippet,
        content=snippet,
        score=0.8,
    )


def test_firecrawl_selective_trigger(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    runtime.config.min_tier_ab_sources = 1

    tavily_docs = [
        _doc(
            "tavily",
            "API authentication guide",
            "https://example.org/api-auth-guide",
            "Authentication should use token validation and scoped permissions.",
        ),
        _doc(
            "tavily",
            "Security architecture",
            "https://example.org/security-architecture",
            "Defense-in-depth improves resilience in distributed systems.",
        ),
    ]
    ddg_docs = [
        _doc(
            "ddg",
            "Threat modeling overview",
            "https://owasp.org/www-community/Threat_Modeling",
            "Threat modeling identifies likely risks and mitigations.",
        )
    ]
    firecrawl_docs = [
        _doc(
            "firecrawl",
            "Docs extract",
            "https://example.com/docs",
            "Endpoint documentation includes auth requirements and scopes.",
        )
    ]
    runtime.mcp_client.web_server.tavily_search = lambda query, k=5: tavily_docs
    runtime.mcp_client.web_server.ddg_search = lambda query, k=5: ddg_docs
    runtime.mcp_client.web_server.firecrawl_extract = (
        lambda url_or_query, mode="extract": firecrawl_docs
    )
    monkeypatch.setattr(
        GraphRuntime,
        "get_llm_client",
        lambda self, provider: (_ for _ in ()).throw(RuntimeError("offline test client")),
    )

    state_without = run_graph("Compare LLM orchestration frameworks", runtime)
    assert state_without.get("firecrawl_requested") is False

    state_with = run_graph("Review https://example.com/docs API authentication", runtime)
    assert state_with.get("firecrawl_requested") is True
    assert "firecrawl_docs" in state_with
