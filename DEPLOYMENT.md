# Cloud Hive Deployment Guide

**Version**: 1.0.0
**Date**: 2026-02-13

## Prerequisites
- **Docker** & **Docker Compose**
- **Python 3.11+**
- **Node.js 18+**
- **PostgreSQL 16+** (External or via Docker)
- **Redis 7+** (External or via Docker)

## 1. Environment Configuration
Create a `.env` file for production. Ensure you set strong secrets.

```bash
# Security
SECRET_KEY=production_secret_key_change_me
ALLOWED_HOSTS=hive.example.com

# Database (Required)
DATABASE_URL=postgresql+asyncpg://user:pass@db-host:5432/cloudhive

# AI Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-...
GROQ_API_KEY=gsk_...
TAVILY_API_KEY=tvly-...

# Deep-research integrity defaults
RESEARCH_DEPTH=deep
RESEARCH_MODE=peak
PRIMARY_SOURCE_POLICY=strict
SOURCE_POLICY=external_only
NO_SOURCE_MODE=fail_closed
REPORT_STYLE=brief_appendix
SOURCE_QUALITY_BAR=high_confidence
SHOW_TECHNICAL_SECTIONS_DEFAULT=false
STARTUP_GUARD_MODE=hybrid
JUDGE_JSON_MODE=repair_retry_fallback
DUAL_USE_DEPTH=dynamic_defensive
TRUTH_MODE=balanced
CLAIM_POLICY=adaptive_scoring
EVIDENCE_FLOOR_MODE=adaptive
INSUFFICIENT_EVIDENCE_OUTPUT=constrained_actionable
QUERY_CLEANUP_MODE=aggressive
NARRATIVE_CITATION_DENSITY=light_inline
MIN_CLAIM_CONFIDENCE_TO_ASSERT=0.62
MAX_UNVERIFIED_CLAIM_RATIO=0.20
REQUIRE_CONTRADICTION_SCAN=true
CONTRADICTION_SCAN_REQUIRED=true
MAX_SOURCES_SNAPSHOT=6
MIN_EXTERNAL_SOURCES=5
MIN_AB_SOURCES=6
MIN_UNIQUE_DOMAINS=6
MIN_UNIQUE_PROVIDERS=2
MIN_TIER_AB_SOURCES=2
MAX_CTIER_CLAIM_RATIO=0.30
MIN_PRIMARY_CLAIMS=8
MAX_PLANNER_TASKS_PEAK=8
AUTO_RETRY_FOR_QUALITY=true
AUTO_RETRY_QUALITY_PASSES=1
REQUIRE_CORROBORATION_FOR_TIER_C=true
MIN_REPORT_WORDS_DEEP=2200
MIN_CLAIMS_DEEP=10
TARGET_REPORT_WORDS_PEAK_MIN=2500
TARGET_REPORT_WORDS_PEAK_MAX=3800

# Services
RUNTIME_PROFILE=full
REDIS_URL=redis://redis-host:6379/0
CELERY_BROKER_URL=redis://redis-host:6379/0
```

## 2. Backend Deployment

### Docker (Recommended)
Build and run the entire stack:
```bash
docker compose --profile core --profile distributed --profile observability up -d --build
```
Minimal production-like core only:
```bash
docker compose --profile core up -d --build
```

### Manual
*Run all commands from the project root: `c:\pyPractice\mcp-eval-researcher`*

1.  **Install**: `poetry install --only main`
2.  **Migrate**: `poetry run python -m alembic upgrade head`
3.  **Run API**:
    ```bash
    poetry run uvicorn service.api:app --host 0.0.0.0 --port 8080 --workers 4
    ```
4.  **Run Worker**:
    ```bash
    # Open a new terminal
    poetry run celery -A graph.distributed worker --loglevel=INFO --concurrency=10
    ```

## 3. Frontend Deployment (Next.js)

1.  **Build**:
    ```bash
    cd web-ui
    npm install
    npm run build
    ```
2.  **Start**:
    ```bash
    # Ensure you are inside /web-ui/
    npm start
    ```
    *Ensure `NEXT_PUBLIC_API_URL` or proxy config points to the backend.*

Recommended production UI env:
- `NEXT_PUBLIC_UI_VERSION=v6`
- `NEXT_PUBLIC_DEFAULT_THEME=system`

## 4. Observability
- **Prometheus**: `:9090`
- **Grafana**: `:3002` (Import dashboards from `config/grafana`)
- **Jaeger**: `:16686`

## 5. Maintenance
- **Backups**: Periodically dump the PostgreSQL database.
- **Updates**: Pull latest code, rebuild images, and run `alembic upgrade head`.
- **Quality posture**:
  - keep `SOURCE_POLICY=external_only` for production
  - only relax to `external_preferred` for degraded environments
  - monitor `eval.json` reasons for recurring source-integrity failures
