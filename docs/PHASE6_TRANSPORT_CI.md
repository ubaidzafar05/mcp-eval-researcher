# Phase 6: Transport + CI Baseline

## Goal
Move Cloud Hive from in-process tool calls to true MCP transport using managed `stdio` processes, while establishing deterministic CI quality gates.

## Transport Design
- Runtime wrapper: `mcp_server/transport_runtime.py`
- Servers launched by command:
  - `python -m mcp_server.web_stdio_app`
  - `python -m mcp_server.local_stdio_app`
- Client strategy:
  - `mcp_mode=auto`: transport-first, fallback to in-process
  - `mcp_mode=transport`: strict transport
  - `mcp_mode=inprocess`: legacy path only

## Failure Modes and Handling
- Startup failure:
  - `auto`: switch to in-process and record fallback reason
  - `transport`: fail fast
- Call failure:
  - per-server circuit breaker + fallback in `auto`
- Provider/API variability:
  - deterministic `stub` judge available for tests/CI

## CI Baseline
- Workflow: `.github/workflows/ci.yml`
- Python: 3.11
- Checks:
  - identity preflight (`EXPECTED_GITHUB_OWNER`, default `UbaidZafar`)
  - Ruff lint
  - pytest excluding stress
  - requirements sync check
- Stress workflow is manual dispatch only.

## Local Mirror Commands
```bash
poetry run python -m scripts.preflight_git_identity
poetry run ruff check .
poetry run pytest -q -m "not stress"
poetry run python -m scripts.check_requirements_sync
```

