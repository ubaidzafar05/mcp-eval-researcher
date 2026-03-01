from pathlib import Path

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
        score=0.9,
    )


def test_e2e_happy_path_creates_artifacts(monkeypatch):
    cfg = load_config(
        {
            "interactive_hitl": False,
            "hitl_mode": "never",
            "judge_provider": "stub",
            "mcp_mode": "inprocess",
        }
    )
    runtime = GraphRuntime.from_config(cfg)

    monkeypatch.setattr(
        runtime.mcp_client.web_server,
        "tavily_search",
        lambda q, k=5: [
            _doc(
                "tavily",
                "NIST AI RMF",
                "https://www.nist.gov/itl/ai-risk-management-framework",
                "NIST AI RMF provides guidance for governing AI risks.",
            ),
            _doc(
                "tavily",
                "Cloud architecture patterns",
                "https://learn.microsoft.com/en-us/azure/architecture/patterns/",
                "Architecture patterns improve reliability and scalability.",
            ),
        ],
    )
    monkeypatch.setattr(
        runtime.mcp_client.web_server,
        "ddg_search",
        lambda q, k=5: [
            _doc(
                "ddg",
                "OWASP Top 10 for LLM Apps",
                "https://owasp.org/www-project-top-10-for-large-language-model-applications/",
                "OWASP outlines risks and mitigations for LLM applications.",
            )
        ],
    )
    monkeypatch.setattr(
        runtime.mcp_client.web_server,
        "firecrawl_extract",
        lambda q, mode="extract": [],
    )

    # Force synthesizer/correction fallback paths to avoid network LLM calls.
    monkeypatch.setattr(
        GraphRuntime,
        "get_llm_client",
        lambda self, provider: (_ for _ in ()).throw(RuntimeError("offline test client")),
    )

    state = run_graph("Design robust free-tier LLM pipelines", runtime)
    assert state.get("final_report")
    assert len(state.get("citations", [])) >= 1
    artifacts = Path(state.get("artifacts_path", ""))
    assert artifacts.exists()
    assert (artifacts / "eval.json").exists()
    assert (artifacts / "citations.json").exists()
