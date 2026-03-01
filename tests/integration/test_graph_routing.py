from core.config import load_config
from core.models import RetrievedDoc
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


def _doc(provider: str, idx: int) -> RetrievedDoc:
    return RetrievedDoc(
        provider=provider,  # type: ignore[arg-type]
        title=f"{provider} source {idx}",
        url=f"https://example.com/{provider}/{idx}",
        snippet=(
            "Evidence covering demand, salaries, skills, uncertainty, and scenario planning "
            f"for provider={provider} idx={idx}."
        ),
        content=(
            "Long-form content with methodological caveats, assumptions, and cross-source "
            "comparison details suitable for deterministic routing tests."
        ),
        score=0.8,
    )


def _mock_retrieval(runtime: GraphRuntime) -> None:
    def call_web_tool(tool_name: str, *args, **kwargs):
        del args, kwargs
        if tool_name == "tavily_search":
            return [_doc("tavily", i) for i in range(1, 7)]
        if tool_name == "ddg_search":
            return [_doc("ddg", i) for i in range(1, 7)]
        return []

    runtime.mcp_client.call_web_tool = call_web_tool  # type: ignore[assignment]
    runtime.memory_store.retrieve_similar = lambda query, k=3: []  # type: ignore[assignment]


def test_graph_completes_happy_path():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
            "research_depth": "balanced",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    _mock_retrieval(runtime)
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
            "research_depth": "balanced",
        }
    )
    runtime = GraphRuntime.from_config(cfg)
    _mock_retrieval(runtime)
    state = run_graph("niche ambiguous query with weak context", runtime)
    assert state.get("correction_count", 0) >= 1
    assert state.get("low_confidence") is True
