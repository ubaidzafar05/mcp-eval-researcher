# Cloud Hive v1.2 (Phase 7 Core)

Cloud Hive is a free-tier research engine with LangGraph orchestration, MCP multi-server tooling, deterministic evaluation gates, and production-minded transport controls.

## Architecture
- Graph flow: Planner -> parallel research (Tavily, DDG, selective Firecrawl) -> Synthesizer -> Self-correction -> Eval Gate -> HITL -> Finalize.
- MCP servers:
  - `web-mcp` (`mcp_server/web_stdio_app.py`, `mcp_server/web_streamable_http_app.py`)
  - `local-mcp` (`mcp_server/local_stdio_app.py`, `mcp_server/local_streamable_http_app.py`)
- Runtime transport:
  - `stdio` (managed child-process MCP sessions)
  - `streamable-http` (token-auth HTTP MCP sessions)
  - `auto` mode falls back to in-process adapters when transport startup/calls fail.

## Security Defaults (HTTP Transport)
- Default bind host is localhost: `MCP_HTTP_HOST=127.0.0.1`.
- Bearer token is required by default in HTTP mode (`MCP_AUTH_TOKEN`).
- Non-localhost bind is rejected unless `MCP_ALLOW_EXTERNAL_BIND=true`.
- Insecure no-token mode requires explicit override: `MCP_ALLOW_INSECURE_HTTP=true`.

## Quickstart
1. Install dependencies:
```bash
poetry install
```
2. Copy env template:
```bash
copy .env.example .env
```
3. Optional identity preflight (Ubaid Zafar account context):
```bash
poetry run python -m scripts.preflight_git_identity
```
4. Run doctor:
```bash
poetry run cloud-hive doctor
```
5. Run research:
```bash
poetry run cloud-hive research "Design resilient free-tier AI research systems" --mcp-mode auto --mcp-transport stdio
```

## CLI
- `poetry run cloud-hive research "<query>" --mcp-mode auto --mcp-transport stdio|streamable-http`
- `poetry run cloud-hive doctor`
- `poetry run cloud-hive eval --run-id <id>`
- `poetry run cloud-hive runs --limit 20`
- `poetry run cloud-hive resume --run-id <id>`
- `poetry run cloud-hive stress --suite basic --iterations 10`

## Phase 8 Foundation (Local)
- Tenant context support and tenant-scoped artifacts: `outputs/<tenant_id>/<run_id>/`
- Local run registry + resume flow: `data/run_registry.jsonl`
- Model router scaffold: `agents/model_router.py`
- Plugin registry scaffold: `mcp_server/plugin_registry.py`
- Distributed task entrypoint scaffold: `graph/distributed.py`
- Streaming endpoint scaffold: `POST /research/stream` (SSE)

## Python API
```python
from core.config import load_config
from main import run_research

cfg = load_config(
    {
        "mcp_mode": "auto",
        "mcp_transport": "stdio",
        "judge_provider": "groq",
    }
)
result = run_research("LangGraph retry best practices", config=cfg)
print(result.final_report)
```

## Docker Compose Baseline
1. Copy compose env:
```bash
copy .env.compose.example .env.compose
```
2. Start stack:
```bash
docker compose up --build
```
3. Endpoints:
- API health: `http://localhost:8080/health`
- API metrics: `http://localhost:8080/metrics`
- App Prometheus endpoint: `http://localhost:9010/metrics`

## Observability
- Prometheus metrics:
  - `mcp_call_total{server,tool,transport,status}`
  - `mcp_call_latency_seconds{server,tool,transport}`
  - `transport_fallback_total{reason}`
  - `graph_run_total{status}`
  - `graph_run_duration_seconds`
- `doctor` reports transport mode, endpoint health, token readiness, and fallback state.
- LangSmith tracing remains compatible via `LANGSMITH_API_KEY`.

## Requirements Sync Workflow
- Export from Poetry:
```bash
poetry run python -m scripts.export_requirements
```
- Verify sync:
```bash
poetry run python -m scripts.check_requirements_sync
```

## Local Smoke Validation
Run local transport-level smoke checks (no GitHub dependency):
```bash
poetry run python -m scripts.local_stack_smoke
```
or:
```bash
make smoke-local
```

## CI
- PR/Push workflow: `.github/workflows/ci.yml`
  - identity preflight
  - `ruff check .`
  - `pytest -q -m "not stress"`
  - requirements sync check
  - `docker compose config` validation (non-blocking)
- Manual stress workflow: `.github/workflows/stress.yml`

## Artifacts
Each run writes to `outputs/<run_id>/`:
- `final_report.md`
- `citations.json`
- `eval.json`

Run metadata is also stored in:
- `data/run_registry.jsonl`

