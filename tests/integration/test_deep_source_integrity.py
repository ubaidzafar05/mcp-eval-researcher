from core.config import load_config
from core.models import RetrievedDoc
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _external_doc(provider: str, idx: int) -> RetrievedDoc:
    snippet = (
        f"{provider} evidence {idx}: demand trends, compensation ranges, required skills, "
        "adoption blockers, and scenario assumptions from externally published analysis."
    )
    content = (
        f"{snippet} This source discusses methodological caveats, timeline assumptions, "
        "and contrasting viewpoints to support claim-level citation mapping."
    )
    return RetrievedDoc(
        provider=provider,  # type: ignore[arg-type]
        title=f"{provider} source {idx}",
        url=f"https://example.com/{provider}/{idx}",
        snippet=snippet,
        content=content,
        score=0.8,
    )


def test_mixed_context_only_external_citations(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "source_policy": "external_only",
            "research_depth": "balanced",
            "min_external_sources": 2,
            "min_unique_providers": 2,
            "min_report_words_deep": 150,
            "min_claims_deep": 2,
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    def call_web_tool(tool_name: str, *args, **kwargs):
        del args, kwargs
        if tool_name == "tavily_search":
            return [_external_doc("tavily", 1), _external_doc("tavily", 2)]
        if tool_name == "ddg_search":
            return [_external_doc("ddg", 1), _external_doc("ddg", 2)]
        return []

    monkeypatch.setattr(runtime.mcp_client, "call_web_tool", call_web_tool)
    monkeypatch.setattr(
        runtime.memory_store,
        "retrieve_similar",
        lambda query, k=3: [
            RetrievedDoc(
                provider="memory",
                title="Memory",
                url="",
                snippet="memory-only context",
                content="memory-only context",
                score=0.2,
            )
        ],
    )

    state = run_graph("Compare AI and ML engineer demand", runtime)
    citations = state.get("citations", [])
    assert citations
    assert all(c.provider in {"tavily", "ddg", "firecrawl"} for c in citations)
    assert all(c.source_url.startswith("http") for c in citations)


def test_fail_closed_when_no_external_sources(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "source_policy": "external_only",
            "no_source_mode": "fail_closed",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    monkeypatch.setattr(runtime.mcp_client, "call_web_tool", lambda *args, **kwargs: [])
    monkeypatch.setattr(runtime.memory_store, "retrieve_similar", lambda query, k=3: [])

    state = run_graph("future of ai engineers", runtime)
    report = state.get("final_report", "")
    assert "Insufficient external evidence" in report
    assert state.get("citations", []) == []


def test_deep_mode_report_meets_multi_page_thresholds(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "source_policy": "external_only",
            "research_depth": "deep",
            "min_external_sources": 5,
            "min_unique_providers": 2,
            "min_report_words_deep": 2200,
            "min_claims_deep": 10,
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    def call_web_tool(tool_name: str, *args, **kwargs):
        del args, kwargs
        if tool_name == "tavily_search":
            return [_external_doc("tavily", i) for i in range(1, 13)]
        if tool_name == "ddg_search":
            return [_external_doc("ddg", i) for i in range(1, 13)]
        return []

    monkeypatch.setattr(runtime.mcp_client, "call_web_tool", call_web_tool)
    monkeypatch.setattr(runtime.memory_store, "retrieve_similar", lambda query, k=3: [])
    monkeypatch.setattr(
        GraphRuntime,
        "get_llm_client",
        lambda self, _provider: (_ for _ in ()).throw(Exception("offline")),
    )

    state = run_graph("future of ai engineers vs ml engineers", runtime)
    report = state.get("final_report", "")
    citations = state.get("citations", [])

    import re

    word_count = len(re.findall(r"\b[\w'-]+\b", report))
    claim_count = len(set(re.findall(r"\[C\d+\]", report)))
    source_section = report.lower().split("## sources used")[-1]
    url_count = len(re.findall(r"https?://\S+", source_section))

    assert word_count >= 2200
    assert claim_count >= 10
    assert url_count >= 5
    assert len(citations) >= 10
