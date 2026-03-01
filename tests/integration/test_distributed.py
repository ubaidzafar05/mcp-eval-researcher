
from unittest.mock import MagicMock, patch

import pytest

from core.models import RunConfig
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime


@pytest.fixture
def mock_runtime():
    config = RunConfig(tenant_id="test-tenant", enable_distributed=True)
    runtime = MagicMock(spec=GraphRuntime)
    runtime.config = config
    return runtime

@patch("graph.distributed.wait_for_distributed_result")
@patch("graph.distributed.dispatch_distributed_task")
@patch("graph.distributed.is_distributed_ready")
def test_run_graph_distributed(
    mock_is_distributed_ready,
    mock_dispatch_distributed_task,
    mock_wait_for_distributed_result,
    mock_runtime,
):
    mock_is_distributed_ready.return_value = (True, "ok")
    mock_task_instance = MagicMock()
    mock_task_instance.id = "test-task-id"
    mock_dispatch_distributed_task.return_value = mock_task_instance
    mock_wait_for_distributed_result.return_value = {
        "run_id": "dist-run-123",
        "query": "test query",
        "status": "completed",
        "final_report": "Distributed report",
        "artifacts_path": "/tmp/artifacts",
        "citations": [],
        "eval_result": {},
    }

    # Run graph in distributed mode
    result = run_graph("test query", mock_runtime, distributed=True)

    # Verify readiness and dispatch
    mock_is_distributed_ready.assert_called_once()
    mock_dispatch_distributed_task.assert_called_once_with(
        query="test query",
        run_id=None,
        tenant_id="test-tenant",
    )

    # Verify wait helper usage
    mock_wait_for_distributed_result.assert_called_once_with(
        mock_task_instance,
        queue_wait_seconds=mock_runtime.config.distributed_queue_wait_seconds,
        result_timeout_seconds=15,
    )

    # Verify result mapping
    assert result["run_id"] == "dist-run-123"
    assert result["status"] == "completed"
    assert result["final_report"] == "Distributed report"
