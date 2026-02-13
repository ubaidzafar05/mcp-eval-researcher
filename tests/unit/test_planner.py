from graph.nodes.planner import _build_tasks, _should_use_firecrawl


def test_planner_builds_max_three_tasks():
    tasks = _build_tasks("mcp research architecture", max_tasks=3)
    assert len(tasks) == 3
    assert tasks[0].tool_hint == "tavily"
    assert tasks[1].tool_hint == "ddg"


def test_planner_triggers_firecrawl_for_docs_query():
    query = "https://example.com/docs API rate limits"
    assert _should_use_firecrawl(query) is True
    tasks = _build_tasks(query, max_tasks=3)
    assert any(task.firecrawl_needed for task in tasks)

