from __future__ import annotations

import re

from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _extract_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    return match.group(0) if match else None


def create_research_firecrawl_node(runtime: GraphRuntime):
    def firecrawl_node(state: ResearchState) -> dict:
        if not state.get("firecrawl_requested", False):
            return {
                "firecrawl_docs": [],
                "logs": ["Firecrawl skipped (not requested by planner)."],
            }

        target = _extract_url(state["query"]) or state["query"]
        docs = runtime.mcp_client.call_web_tool("firecrawl_extract", target, "extract")
        runtime.tracer.event(
            state["run_id"],
            "research_firecrawl",
            "Collected firecrawl docs",
            payload={"doc_count": len(docs)},
        )
        return {
            "firecrawl_docs": docs,
            "logs": [f"Firecrawl researcher collected {len(docs)} docs."],
        }

    return firecrawl_node
