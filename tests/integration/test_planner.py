
import pytest
from unittest.mock import MagicMock
from graph.nodes.planner import create_planner_node
from graph.runtime import GraphRuntime
from core.models import RunConfig, TaskSpec

@pytest.fixture
def mock_runtime():
    config = RunConfig(max_tasks=3)
    runtime = MagicMock(spec=GraphRuntime)
    runtime.config = config
    runtime.model_router = MagicMock()
    runtime.get_llm_client = MagicMock()
    runtime.memory_store = MagicMock()
    runtime.memory_store.retrieve_similar.return_value = []
    
    # Mock Select Model
    mock_selection = MagicMock()
    mock_selection.provider = "openai"
    mock_selection.model_name = "gpt-4"
    runtime.model_router.select_model.return_value = mock_selection
    
    return runtime

def test_planner_adaptive(mock_runtime):
    # Setup Mock LLM Response
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = """
    {
        "tasks": [
            {"title": "Task 1", "search_query": "query 1", "tool_hint": "tavily", "priority": 1},
            {"title": "Task 2", "search_query": "query 2", "tool_hint": "ddg", "priority": 2}
        ]
    }
    """
    mock_runtime.get_llm_client.return_value = mock_client
    
    # Execute
    node = create_planner_node(mock_runtime)
    state = {"query": "complex query", "run_id": "test-run"}
    result = node(state)
    
    # Verify
    mock_runtime.model_router.select_model.assert_called_with(
        task_type="planning",
        context_size=0,
        latency_budget_ms=3000,
        tenant_tier="default"
    )
    mock_runtime.get_llm_client.assert_called_with("openai")
    
    tasks = result["tasks"]
    assert len(tasks) == 2
    assert tasks[0].title == "Task 1"
    assert tasks[1].search_query == "query 2"

def test_planner_fallback(mock_runtime):
    # Setup Mock LLM Failure
    mock_runtime.get_llm_client.side_effect = Exception("LLM Error")
    
    # Execute
    node = create_planner_node(mock_runtime)
    state = {"query": "complex query", "run_id": "test-run"}
    result = node(state)
    
    # Verify Fallback (Default is 3 tasks)
    tasks = result["tasks"]
    assert len(tasks) == 3
    assert tasks[0].title == "Core Facts"
