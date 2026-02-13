
import pytest
from unittest.mock import MagicMock, patch
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime
from core.models import RunConfig

@pytest.fixture
def mock_runtime():
    config = RunConfig(tenant_id="test-tenant")
    runtime = MagicMock(spec=GraphRuntime)
    runtime.config = config
    return runtime

@patch("graph.distributed.execute_research_task")
def test_run_graph_distributed(mock_execute_task, mock_runtime):
    # Setup mock task
    mock_task_instance = MagicMock()
    mock_task_instance.id = "test-task-id"
    mock_task_instance.get.return_value = {
        "run_id": "dist-run-123",
        "query": "test query",
        "status": "completed",
        "final_report": "Distributed report",
        "artifacts_path": "/tmp/artifacts"
    }
    mock_execute_task.delay.return_value = mock_task_instance

    # Run graph in distributed mode
    result = run_graph("test query", mock_runtime, distributed=True)

    # Verify dispatch
    mock_execute_task.delay.assert_called_once_with(
        query="test query",
        run_id=None,
        tenant_id="test-tenant"
    )

    # Verify usage of task.get()
    mock_task_instance.get.assert_called_once()

    # Verify result mapping
    assert result["run_id"] == "dist-run-123"
    assert result["status"] == "completed"
    assert result["final_report"] == "Distributed report"
