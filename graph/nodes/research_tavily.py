from __future__ import annotations

from core.models import TaskSpec
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def create_research_tavily_node(runtime: GraphRuntime):
    def tavily_node(state: ResearchState) -> dict:
        tasks = state.get("tasks", [])
        task_queries = [
            task.search_query
            for task in tasks
            if isinstance(task, TaskSpec) and task.tool_hint in {"tavily", "any"}
        ]
        if not task_queries:
            task_queries = [state["query"]]
        docs = []
        for query in task_queries[:2]:
            docs.extend(runtime.mcp_client.call_web_tool("tavily_search", query, 5))
        runtime.tracer.event(
            state["run_id"],
            "research_tavily",
            "Collected tavily docs",
            payload={"doc_count": len(docs)},
        )
        return {
            "tavily_docs": docs,
            "logs": [f"Tavily researcher collected {len(docs)} docs."],
        }

    return tavily_node
