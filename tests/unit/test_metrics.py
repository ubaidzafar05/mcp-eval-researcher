from core.metrics import (
    GRAPH_RUN_TOTAL,
    MCP_CALL_TOTAL,
    TRANSPORT_FALLBACK_TOTAL,
    record_graph_run,
    record_mcp_call,
    record_transport_fallback,
)


def test_record_mcp_call_increments_counter():
    labels = {
        "server": "web",
        "tool": "tavily_search",
        "transport": "stdio",
        "status": "success",
    }
    before = MCP_CALL_TOTAL.labels(**labels)._value.get()
    record_mcp_call(**labels, duration_seconds=0.01)
    after = MCP_CALL_TOTAL.labels(**labels)._value.get()
    assert after == before + 1


def test_record_transport_fallback_increments_counter():
    reason = "unit-test-fallback"
    before = TRANSPORT_FALLBACK_TOTAL.labels(reason=reason)._value.get()
    record_transport_fallback(reason)
    after = TRANSPORT_FALLBACK_TOTAL.labels(reason=reason)._value.get()
    assert after == before + 1


def test_record_graph_run_increments_counter():
    before = GRAPH_RUN_TOTAL.labels(status="completed")._value.get()
    record_graph_run(status="completed", duration_seconds=0.02)
    after = GRAPH_RUN_TOTAL.labels(status="completed")._value.get()
    assert after == before + 1
