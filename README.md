# Cloud Hive v1.3 (Phase 8 Scalability & Intelligence)

Cloud Hive is a free-tier research engine with LangGraph orchestration, distributed task execution, dynamic model routing, and adaptive planning.

## Architecture
- **Graph flow**: Adaptive Planner -> Parallel Research (Tavily/DDG/Firecrawl) -> Distributed Synthesizer -> Self-correction -> Eval Gate -> HITL -> Finalize.
- **Distributed Execution**: Celery + Redis for asynchronous task processing.
- **Model Router**: Dynamic selection of LLMs (Groq, OpenAI, Anthropic) based on task type and complexity.
- **MCP servers**:
  - `web-mcp` (`mcp_server/web_stdio_app.py`, `mcp_server/web_streamable_http_app.py`)
  - `local-mcp` (`mcp_server/local_stdio_app.py`, `mcp_server/local_streamable_http_app.py`)

## Key Features (v1.3)
- **Adaptive Planning**: LLM-generated research plans tailored to query complexity.
- **Distributed Execution**: Heavy tasks (research, synthesis) offloaded to Celery workers.
- **Model Routing**: 
  - **Synthesizer**: Uses high-capacity models (e.g., GPT-4, Claude Opus) for complex reports.
  - **Evaluator**: Uses fast models (e.g., Llama 3 via Groq) for gating.
  - **Corrector**: Uses robust models for self-correction.
- **Tenant Context**: Tier-based quotas and routing strategies (`free`, `pro`, `enterprise`).

## Quickstart

### 1. Install Dependencies
```bash
poetry install
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

### 3. Start Infrastructure (Redis + Workers)
```bash
docker compose up -d redis celery-worker
```

### 4. Run Research
```bash
poetry run cloud-hive research "Future of AI Agents" --mcp-mode auto
```

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

## Observability
- **Prometheus Metrics**: `http://localhost:9010/metrics`
- **LangSmith Tracing**: Enable via `LANGSMITH_API_KEY`.
- **Logs**: Structured logs in `logs/` directory.

## Testing
Run the test suite, including new integration tests for routing and planning:
```bash
poetry run pytest tests/integration/
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
