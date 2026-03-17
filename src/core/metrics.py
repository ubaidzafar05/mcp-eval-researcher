from __future__ import annotations

import threading

from prometheus_client import Counter, Histogram, start_http_server

_METRICS_LOCK = threading.Lock()
_METRICS_SERVER_STARTED = False

MCP_CALL_TOTAL = Counter(
    "mcp_call_total",
    "Total MCP tool calls.",
    ["server", "tool", "transport", "status"],
)
MCP_CALL_LATENCY_SECONDS = Histogram(
    "mcp_call_latency_seconds",
    "MCP tool call latency in seconds.",
    ["server", "tool", "transport"],
)
TRANSPORT_FALLBACK_TOTAL = Counter(
    "transport_fallback_total",
    "Total number of transport fallbacks by reason.",
    ["reason"],
)
GRAPH_RUN_TOTAL = Counter(
    "graph_run_total",
    "Total graph runs by status.",
    ["status"],
)
GRAPH_RUN_DURATION_SECONDS = Histogram(
    "graph_run_duration_seconds",
    "Graph run duration in seconds.",
)
FALLBACK_CLAIM_TOTAL = Counter(
    "fallback_claim_total",
    "Total fallback claims generated.",
)
EMPTY_EXTRACTION_TOTAL = Counter(
    "empty_extraction_total",
    "Total empty claim extractions.",
    ["reason"],
)
REPORT_SUCCESS_TOTAL = Counter(
    "report_success_total",
    "Total reports generated successfully.",
    ["status"],
)
REPORT_FAILURE_TOTAL = Counter(
    "report_failure_total",
    "Total report failures.",
    ["status"],
)


def ensure_metrics_server(host: str, port: int) -> None:
    global _METRICS_SERVER_STARTED
    with _METRICS_LOCK:
        if _METRICS_SERVER_STARTED:
            return
        start_http_server(port=port, addr=host)
        _METRICS_SERVER_STARTED = True


def record_mcp_call(
    *,
    server: str,
    tool: str,
    transport: str,
    status: str,
    duration_seconds: float,
) -> None:
    MCP_CALL_TOTAL.labels(
        server=server,
        tool=tool,
        transport=transport,
        status=status,
    ).inc()
    MCP_CALL_LATENCY_SECONDS.labels(
        server=server,
        tool=tool,
        transport=transport,
    ).observe(max(0.0, duration_seconds))


def record_transport_fallback(reason: str) -> None:
    TRANSPORT_FALLBACK_TOTAL.labels(reason=reason or "unknown").inc()


def record_graph_run(status: str, duration_seconds: float) -> None:
    GRAPH_RUN_TOTAL.labels(status=status).inc()
    GRAPH_RUN_DURATION_SECONDS.observe(max(0.0, duration_seconds))


def record_fallback_claims(count: int) -> None:
    FALLBACK_CLAIM_TOTAL.inc(max(0, int(count)))


def record_empty_extraction(reason: str) -> None:
    EMPTY_EXTRACTION_TOTAL.labels(reason=reason or "unknown").inc()


def record_report_success(status: str) -> None:
    REPORT_SUCCESS_TOTAL.labels(status=status or "unknown").inc()


def record_report_failure(status: str) -> None:
    REPORT_FAILURE_TOTAL.labels(status=status or "unknown").inc()
