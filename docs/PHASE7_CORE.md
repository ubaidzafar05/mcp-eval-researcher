# Phase 7 Core: Dual Transport, Security Defaults, and Ops Baseline

## Goal
Advance Cloud Hive beyond Phase 6 by adding optional HTTP MCP transport, secure-by-default token auth, container baseline, and transport-aware observability.

## Transport Model
- `stdio` remains fully supported and unchanged.
- `streamable-http` is additive and selected via `MCP_TRANSPORT=streamable-http`.
- `MCP_MODE` behavior:
  - `auto`: try selected transport, then degrade to in-process adapters.
  - `transport`: strict mode, fail fast when transport is unavailable.
  - `inprocess`: bypass transport entirely.

## HTTP Security Defaults
- Local bind default: `MCP_HTTP_HOST=127.0.0.1`.
- Token required by default: `MCP_AUTH_TOKEN`.
- External bind blocked unless `MCP_ALLOW_EXTERNAL_BIND=true`.
- Token bypass blocked unless `MCP_ALLOW_INSECURE_HTTP=true`.

## Deployment Baseline
- `Dockerfile` for app/runtime packaging.
- `docker-compose.yml` stack:
  - `app`
  - `web-mcp-http`
  - `local-mcp-http`
- Service health checks are included for all three services.

## Metrics and Logs
- Prometheus counters/histograms:
  - `mcp_call_total{server,tool,transport,status}`
  - `mcp_call_latency_seconds{server,tool,transport}`
  - `transport_fallback_total{reason}`
  - `graph_run_total{status}`
  - `graph_run_duration_seconds`
- Runtime logs continue to include `run_id`, node, and fallback context.

## Failure Modes and Handling
- HTTP transport startup failure:
  - `auto`: fallback to in-process path.
  - `transport`: explicit error.
- Auth mismatch:
  - strict transport path does not silently fallback.
- Endpoint unreachability:
  - tracked through fallback metrics and doctor visibility.

## Test Determinism
- CI keeps deterministic routing via `judge_provider=stub`.
- HTTP transport integration tests cover:
  - successful path,
  - unreachable endpoint fallback in `auto`,
  - auth failure behavior in strict mode.

## Next-Phase Hooks
- Expand HTTP transport to remote deployment packaging.
- Add dashboards for transport-level latency/error SLOs.
- Add stream-level telemetry and richer health probes.
