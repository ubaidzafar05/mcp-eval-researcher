
import pytest
from unittest.mock import MagicMock, patch
from core.observability import TraceManager
from core.models import RunConfig

def test_trace_manager_otlp_export():
    config = RunConfig(
        run_id="test-run",
        otel_enabled=True,
        otel_endpoint="http://localhost:4317"
    )
    
    with patch("core.observability.trace") as mock_trace:
        mock_tracer = MagicMock()
        mock_trace.get_tracer.return_value = mock_tracer
        
        manager = TraceManager(config)
        manager.event("test-run", "test-node", "test-message", payload={"foo": "bar"})
        
        # Verify tracer was obtained
        mock_trace.get_tracer.assert_called_with("cloud-hive")
        
        # Verify span was started
        mock_tracer.start_as_current_span.assert_called_with("test-node")
        
def test_trace_manager_no_otel():
    config = RunConfig(run_id="test-run", otel_enabled=False)
    
    with patch("core.observability.trace") as mock_trace:
        manager = TraceManager(config)
        manager.event("test-run", "test-node", "test-message")
        
        # Should NOT use otel
        mock_trace.get_tracer.assert_not_called()
