# Cloud Hive v1.1 (Phase 6)

Cloud Hive is a free-tier research engine with LangGraph orchestration, true MCP transport (`stdio`), deterministic CI checks, and claim-level quality gating.

## Architecture
- LangGraph flow: Planner -> parallel research (Tavily, DDG, selective Firecrawl) -> Synthesizer -> Self-correction -> Eval Gate -> HITL -> Finalize.
- MCP servers:
  - `web-mcp` (`mcp_server/web_stdio_app.py`)
  - `local-mcp` (`mcp_server/local_stdio_app.py`)
- `MultiServerClient` defaults to `mcp_mode=auto`:
  - tries transport first,
  - falls back to in-process adapters if startup/calls fail.

## MCP Modes
- `MCP_MODE=auto`: transport-first with safe fallback.
- `MCP_MODE=transport`: strict transport, fails fast if unavailable.
- `MCP_MODE=inprocess`: direct Python adapters only.

## Quickstart
1. Install dependencies:
```bash
poetry install
```
2. Copy env template:
```bash
copy .env.example .env
```
3. Preflight identity check (Ubaid Zafar account context):
```bash
poetry run python -m scripts.preflight_git_identity
```
4. Doctor:
```bash
poetry run cloud-hive doctor
```
5. Run research:
```bash
poetry run cloud-hive research "Design resilient free-tier AI research systems"
```

## CLI
- `poetry run cloud-hive research "<query>" --mcp-mode auto`
- `poetry run cloud-hive doctor`
- `poetry run cloud-hive eval --run-id <id>`
- `poetry run cloud-hive stress --suite basic --iterations 10`

## Python API
```python
from core.config import load_config
from main import run_research

cfg = load_config({"mcp_mode": "auto", "judge_provider": "groq"})
result = run_research("LangGraph retry best practices", config=cfg)
print(result.final_report)
```

## Requirements Sync Workflow
- Export from Poetry:
```bash
poetry run python -m scripts.export_requirements
```
- Check sync:
```bash
poetry run python -m scripts.check_requirements_sync
```

## CI
- PR/Push workflow: `.github/workflows/ci.yml`
  - identity preflight
  - `ruff check .`
  - `pytest -q -m "not stress"`
  - requirements sync check
- Manual stress workflow: `.github/workflows/stress.yml`

## Output Artifacts
Each run writes to `outputs/<run_id>/`:
- `final_report.md`
- `citations.json`
- `eval.json`

