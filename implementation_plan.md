# Implementation Plan - Phase 9: Observability

The goal is to provide production-grade visibility into the Cloud Hive system using a standard open-source stack.

## User Review Required

> [!NOTE]
> This creates 3 new containers (Prometheus, Grafana, Jaeger). Ensure your Docker host has sufficient memory (~1GB extra).

## Proposed Changes

### 1. Infrastructure (Docker Compose)
#### [MODIFY] [docker-compose.yml](file:///c:/pyPractice/mcp-eval-researcher/docker-compose.yml)
- Add `prometheus` service (port 9090).
- Add `grafana` service (port 3000).
- Add `jaeger` service (port 16686 UI, 4317 OTLP).

### 2. Configuration Files
#### [NEW] [config/prometheus/prometheus.yml](file:///c:/pyPractice/mcp-eval-researcher/config/prometheus/prometheus.yml)
- Scrape config for `app`, `web-mcp`, `local-mcp`, `celery-worker`.

#### [NEW] [config/grafana/provisioning/datasources/datasource.yml](file:///c:/pyPractice/mcp-eval-researcher/config/grafana/provisioning/datasources/datasource.yml)
- Auto-provision Prometheus as a data source.

### 3. Application Instrumentation
#### [MODIFY] [core/observability.py](file:///c:/pyPractice/mcp-eval-researcher/core/observability.py)
- Integrate `opentelemetry-instrumentation`.
- Configure OTLP exporter to send traces to Jaeger.

### 4. Verification Plan
#### Automated Tests
- Create `tests/integration/test_observability.py`.
- Verify `/metrics` endpoint is reachable.
- Verify traces are generated on graph run.

#### Manual Verification
- Open Grafana (http://localhost:3000) and view metrics.
- Open Jaeger (http://localhost:16686) and view traces for a research run.
