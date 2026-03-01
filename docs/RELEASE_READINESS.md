# Release Readiness Checklist

## Quality Gates
- `poetry run ruff check .`
- `poetry run mypy --explicit-package-bases agents cli core evals graph memory mcp_server service main.py`
- `poetry run pytest -q -m "not stress"`
- `poetry run pytest -q -m stress`

## Runtime Smoke
- Local stack transport smoke:
  - `poetry run python scripts/local_stack_smoke.py`
- Minimal provider smoke (low quota usage):
  - `poetry run python scripts/provider_smoke_minimal.py`
- Profile diagnostics:
  - `poetry run cloud-hive doctor --profile minimal`
  - `poetry run cloud-hive doctor --profile balanced`
  - `poetry run cloud-hive doctor --profile full`

## Security and Config
- Confirm `.env` has required provider keys only.
- If `LANGSMITH_API_KEY` is org-scoped, set `LANGSMITH_WORKSPACE_ID`.
- Keep HTTP MCP bind on localhost unless explicitly required:
  - `MCP_HTTP_HOST=127.0.0.1`
  - `MCP_ALLOW_EXTERNAL_BIND=false`
  - `MCP_AUTH_TOKEN` and `MCP_CLIENT_AUTH_TOKEN` configured.

## Operational Checks
- `poetry run cloud-hive doctor`
- `GET /health/deps` returns runtime profile and subsystem readiness reasons.
- Verify output artifacts in `outputs/<run_id>/`
- Verify logs in `logs/cloud_hive.log`
- Validate retention policy by confirming old artifacts cleanup.

## Release Notes Inputs
- Include test/lint/type-check status.
- Include known skipped tests (`tests/e2e/test_frontend.py` if frontend server not running).
- Include provider availability notes (pass/skip/fail from minimal smoke).
