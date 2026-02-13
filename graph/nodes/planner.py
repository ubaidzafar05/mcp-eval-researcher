from __future__ import annotations

import re

from core.models import TaskSpec
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _should_use_firecrawl(query: str) -> bool:
    query_l = query.lower()
    keywords = (
        "docs",
        "documentation",
        "api",
        "tutorial",
        "guide",
        "changelog",
        "release notes",
    )
    has_url = bool(re.search(r"https?://\S+", query))
    return has_url or any(token in query_l for token in keywords)


def _build_tasks(query: str, max_tasks: int) -> list[TaskSpec]:
    firecrawl_needed = _should_use_firecrawl(query)
    tasks = [
        TaskSpec(
            id=1,
            title="Core Facts",
            search_query=query,
            tool_hint="tavily",
            priority=1,
        ),
        TaskSpec(
            id=2,
            title="Latest Signals",
            search_query=f"{query} latest developments",
            tool_hint="ddg",
            priority=2,
        ),
        TaskSpec(
            id=3,
            title="Deep Source Extraction" if firecrawl_needed else "Risks and Tradeoffs",
            search_query=query,
            tool_hint="firecrawl" if firecrawl_needed else "any",
            priority=3,
            firecrawl_needed=firecrawl_needed,
        ),
    ]
    return tasks[: max(1, max_tasks)]


def create_planner_node(runtime: GraphRuntime):
    def planner_node(state: ResearchState) -> dict:
        query = state["query"]
        tasks = _build_tasks(query, runtime.config.max_tasks)
        memory_docs = runtime.memory_store.retrieve_similar(query=query, k=3)
        firecrawl_requested = any(task.firecrawl_needed for task in tasks)
        runtime.tracer.event(
            state["run_id"],
            "planner",
            "Built plan tasks",
            payload={"task_count": len(tasks), "firecrawl_requested": firecrawl_requested},
        )
        return {
            "tasks": tasks,
            "memory_docs": memory_docs,
            "firecrawl_requested": firecrawl_requested,
            "status": "planned",
            "logs": [f"Planner created {len(tasks)} tasks."],
        }

    return planner_node

