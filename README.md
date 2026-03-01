# Cloud Hive v1.3 (Phase 8 Scalability & Intelligence)

Cloud Hive is a free-tier research engine with LangGraph orchestration, distributed task execution, dynamic model routing, and adaptive planning.

## Architecture
- **Graph flow**: Adaptive Planner -> Parallel Research (Tavily/DDG/Firecrawl) -> Distributed Synthesizer -> Self-correction -> Eval Gate -> HITL -> Finalize.
- **Distributed Execution**: Celery + Redis for asynchronous task processing.
- **Model Router**: Dynamic selection of LLMs (Groq, OpenAI, Anthropic) based on task type and complexity.
- **MCP servers**:
  - `web-mcp` (`mcp_server/web_stdio_app.py`, `mcp_server/web_streamable_http_app.py`)
  - `local-mcp` (`mcp_server/local_stdio_app.py`, `mcp_server/local_streamable_http_app.py`)

## Runtime Profiles
Cloud Hive now defaults to **minimal core** for reliability and lower local overhead.

- `minimal` (default):
  - API + UI + MCP core path
  - inline execution
  - no Redis/Celery required
  - observability stack disabled by default
- `balanced`:
  - everything in minimal
  - distributed execution enabled (Redis + Celery expected)
  - storage support enabled
- `full`:
  - everything in balanced
  - observability integrations enabled (Prometheus/Grafana/Jaeger)

Set with `RUNTIME_PROFILE=minimal|balanced|full` in `.env`.

## Key Features (v1.3)
- **Adaptive Planning**: LLM-generated research plans tailored to query complexity.
- **Distributed Execution**: Heavy tasks (research, synthesis) offloaded to Celery workers.
- **Model Routing**: 
  - **Synthesizer**: Uses high-capacity models (e.g., GPT-4, Claude Opus) for complex reports.
  - **Evaluator**: Uses fast models (e.g., Llama 3 via Groq) for gating.
  - **Corrector**: Uses robust models for self-correction.
- **Tenant Context**: Tier-based quotas and routing strategies (`free`, `pro`, `enterprise`).
- **Real-time Streaming**: Server-Sent Events (SSE) for live research updates (`GET /research/stream`).
- **Deep Source Integrity**:
  - `SOURCE_POLICY=external_only` by default
  - memory context is non-citable in deep mode
  - fail-closed reporting when no valid external evidence is available

## Deep-Research Defaults
- `RESEARCH_DEPTH=deep`
- `SOURCE_POLICY=external_only`
- `NO_SOURCE_MODE=fail_closed`
- `REPORT_STYLE=brief_appendix`
- `REPORT_PRESENTATION=book`
- `SOURCES_PRESENTATION=cards_with_ledger`
- `SHOW_RAW_SOURCE_LEDGER_DEFAULT=false`
- `METHOD_NARRATIVE_ENABLED=true`
- `STRICT_HIGH_CONFIDENCE=true`
- `TRUTH_MODE=balanced`
- `CLAIM_POLICY=adaptive_scoring`
- `EVIDENCE_FLOOR_MODE=adaptive`
- `INSUFFICIENT_EVIDENCE_OUTPUT=constrained_actionable`
- `QUERY_CLEANUP_MODE=aggressive`
- `NARRATIVE_CITATION_DENSITY=light_inline`
- `MIN_CLAIM_CONFIDENCE_TO_ASSERT=0.62`
- `MAX_UNVERIFIED_CLAIM_RATIO=0.20`
- `REQUIRE_CONTRADICTION_SCAN=true`
- `MAX_SOURCES_SNAPSHOT=6`
- `SOURCE_QUALITY_BAR=high_confidence`
- `DUAL_USE_DEPTH=dynamic_defensive`
- `MIN_EXTERNAL_SOURCES=5` (adaptive lower bound to 2 only under quota-pressure mode)
- `MIN_UNIQUE_PROVIDERS=2`
- `MIN_TIER_AB_SOURCES=2`
- `REQUIRE_CORROBORATION_FOR_TIER_C=true`
- `MIN_REPORT_WORDS_DEEP=2200`
- `MIN_CLAIMS_DEEP=10`

These defaults prioritize provenance and analyst-grade structure over generic narrative output.

## Quickstart

### 1. Install Dependencies
```bash
poetry install
```

### Windows PowerShell (Primary Local Workflow)
From project root:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

`dev.ps1` behavior:
- starts **minimal profile** by default (`web-mcp-http`, `local-mcp-http`, `app`)
- uses Docker stack when Docker daemon is available
- automatically falls back to local backend (`uvicorn`, `MCP_MODE=inprocess`) if Docker is unavailable
- waits for API health before starting UI to avoid endless "Connecting..." in the frontend

Profile variants:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Profile balanced
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Profile full
```

Helpers:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-smoke.ps1
```

### Makefile (Secondary)
From project root:
```bash
make dev             # minimal profile
make dev-up-balanced # balanced profile backend
make dev-up-full     # full profile backend
```

### 2. Configure Environment
Copy `.env.example` to `.env` and configure your keys:
```bash
copy .env.example .env
```
Key variables:
- `REDIS_URL`: Redis connection string (default: `redis://localhost:6379/0`)
- `CELERY_BROKER_URL`: Celery broker (default: `redis://localhost:6379/0`)
- `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`: LLM providers.
- `LANGSMITH_API_KEY`, `LANGSMITH_WORKSPACE_ID`: enable LangSmith tracing (workspace ID required for org-scoped keys).
- `RESEARCH_DEPTH`, `SOURCE_POLICY`, `NO_SOURCE_MODE`: deep quality and provenance controls.
- `RESEARCH_MODE`, `PRIMARY_SOURCE_POLICY`, `SHOW_TECHNICAL_SECTIONS_DEFAULT`: peak mode behavior, strict source policy, and report UX defaults.
- `REPORT_STYLE`, `REPORT_PRESENTATION`, `SOURCES_PRESENTATION`: narrative style and reading layout controls.
- `METHOD_NARRATIVE_ENABLED`, `STRICT_HIGH_CONFIDENCE`, `TRUTH_MODE`, `CLAIM_POLICY`, `EVIDENCE_FLOOR_MODE`: truth and confidence policy controls.
- `INSUFFICIENT_EVIDENCE_OUTPUT`, `QUERY_CLEANUP_MODE`, `NARRATIVE_CITATION_DENSITY`, `MAX_SOURCES_SNAPSHOT`: low-evidence behavior, query cleanup, citation density, and snapshot sizing.
- `SOURCE_QUALITY_BAR`, `DUAL_USE_DEPTH`: source-quality strictness and dynamic safety policy.
- `MIN_EXTERNAL_SOURCES`, `MIN_AB_SOURCES`, `MIN_UNIQUE_DOMAINS`, `MIN_UNIQUE_PROVIDERS`, `MIN_TIER_AB_SOURCES`, `MAX_CTIER_CLAIM_RATIO`: source integrity gate thresholds.
- `MIN_PRIMARY_CLAIMS`, `TARGET_REPORT_WORDS_PEAK_MIN`, `TARGET_REPORT_WORDS_PEAK_MAX`, `AUTO_RETRY_FOR_QUALITY`, `AUTO_RETRY_QUALITY_PASSES`, `CONTRADICTION_SCAN_REQUIRED`: peak quality controls.
- `STARTUP_GUARD_MODE=hybrid|strict`: optional dependency behavior (`hybrid` degrades safely, `strict` blocks startup).
- `JUDGE_JSON_MODE=repair_retry_fallback|strict|heuristic`: judge malformed-JSON recovery policy.

### 3. Start Infrastructure (Redis + Workers)
```bash
docker compose up -d redis celery-worker
```

### 4. Run Research (CLI)
Run from the project root (`c:\pyPractice\mcp-eval-researcher`):
```bash
poetry run cloud-hive research "Future of AI Agents" --mcp-mode auto
```

### 5. Run Web UI (Phase 11)
Start the frontend interface:
```bash
# Open a new terminal
cd web-ui
npm run dev
```
Open `http://localhost:3000`.

Frontend env toggles (`web-ui/.env.example`):
- `NEXT_PUBLIC_UI_VERSION=v6` enables the Editorial Atlas V6 surface.
- `NEXT_PUBLIC_DEFAULT_THEME=system|light|dark` controls initial theme mode.
- `NEXT_PUBLIC_EXECUTION_MODE` and `NEXT_PUBLIC_RUNTIME_PROFILE` set UI runtime defaults.

## CLI
- `poetry run cloud-hive research "<query>"`: Start a new research run.
- `poetry run cloud-hive doctor`: Check system health (including Redis/Celery).
- `poetry run cloud-hive runs`: List recent runs.
- `poetry run cloud-hive resume --run-id <id>`: Resume a suspended run.

## Distributed Execution
To enable distributed execution, ensure Redis is running and workers are started:
```bash
# Start Redis
docker run -d -p 6379:6379 redis:alpine

# Start Worker
poetry run celery -A graph.distributed worker --loglevel=info
```

## Observability (Phase 9)
- **Prometheus**: Metrics at `http://localhost:9090`.
- **Grafana**: Dashboards at `http://localhost:3002` (user: admin, pass: admin).
- **Jaeger**: Traces at `http://localhost:16686`.

To enable full observability:
1. Ensure `docker-compose.yml` services are running.
2. Use `RUNTIME_PROFILE=full` (or explicit `ENABLE_OBSERVABILITY=true`).
3. Set `OTEL_ENABLED=True` in `.env` (or `RunConfig`) if OTEL export is required.

## Dependency Footprint
- Required core dependencies: FastAPI, LangGraph, MCP stack, Tavily/DDG clients, model SDKs, pruning/formatting.
- Optional by profile:
  - Distributed: `celery`, `redis`
  - Observability: `langsmith`, `opentelemetry-*`
  - Storage: `sqlalchemy`, `asyncpg`, `alembic`
  - Eval extras: `deepeval`, `pydantic-ai`

## Testing
Run the test suite, including new integration tests for routing and planning:
```bash
poetry run pytest tests/integration/
```

Recommended quality verification:
```bash
poetry run pytest tests/unit/test_citations.py tests/unit/test_report_quality.py tests/integration/test_deep_source_integrity.py
```

## Docker Compose
Full stack deployment:
```bash
docker compose up --build
```
Services:
- `app`: Main API
- `celery-worker`: Distributed task worker
- `redis`: Message broker & cache
- `web-mcp`: Web search tools
- `local-mcp`: Local file tools

## Development
- **Linting**: `ruff check .`
- **Formatting**: `ruff format .`
- **Type Checking**: `mypy .`

## Deployment
See **[DEPLOYMENT.md](DEPLOYMENT.md)** for production setup instructions.
