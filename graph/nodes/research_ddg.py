from __future__ import annotations

from core.models import TaskSpec
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def create_research_ddg_node(runtime: GraphRuntime):
    def ddg_node(state: ResearchState) -> dict:
        tasks = state.get("tasks", [])
        task_queries = [
            task.search_query
            for task in tasks
            if isinstance(task, TaskSpec) and task.tool_hint in {"ddg", "any"}
        ]
        if not task_queries:
            task_queries = [state["query"]]
        docs = []
        for query in task_queries[:2]:
            docs.extend(runtime.mcp_client.call_web_tool("ddg_search", query, 5))
        runtime.tracer.event(
            state["run_id"],
            "research_ddg",
            "Collected ddg docs",
            payload={"doc_count": len(docs)},
        )
        return {
            "ddg_docs": docs,
            "logs": [f"DDG researcher collected {len(docs)} docs."],
        }

    return ddg_node
