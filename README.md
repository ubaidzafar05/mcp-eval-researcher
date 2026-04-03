# Cloud Hive v1.3

Multi-agent research engine with LangGraph orchestration, MCP tool access, and DeepEval quality gates.

## Architecture
- FastAPI service exposes the research API and streaming endpoints.
- LangGraph planner fans out into parallel research, synthesis, self-correction, and eval steps.
- MCP servers provide web and local tool access for browsing and workspace-style retrieval.
- Redis and Celery support distributed execution when the runtime profile requires it.
- DeepEval gates and source policy keep the system grounded before final output is released.

## Problem + Solution
### Problem
Research agents often move fast but produce weakly grounded, inconsistent reports.

### Solution
Built a source-first research pipeline that routes tools deliberately, evaluates outputs before release, and keeps a human-in-the-loop checkpoint for higher-risk work.

## Tech Stack
Python, FastAPI, LangGraph, MCP, DeepEval, Celery, Redis, ChromaDB, SQLAlchemy, PostgreSQL, OpenAI, Tavily, DDGS, WeasyPrint, Next.js, React, Tailwind, OpenTelemetry, Prometheus.

## Runtime Profiles
- `minimal`: API, UI, and core research flow with inline execution.
- `balanced`: enables distributed execution with Redis and Celery.
- `full`: adds observability integrations.

## Local Run
1. Copy the env files and select a runtime profile.
2. Start the API and UI with the provided Docker or local scripts.
3. Use `cloud-hive` from the CLI to run research workflows.
