# Implementation Plan - Phase 10: Real-time Streaming

The goal is to replace the blocking API endpoint with a true Server-Sent Events (SSE) stream that provides real-time updates on research progress.

## User Review Required

> [!NOTE]
> This introduces a new endpoint `GET /research/stream` which will eventually replace `POST /research`.

## Proposed Changes

### 1. API Layer
#### [NEW] [mcp_server/sse.py](file:///c:/pyPractice/mcp-eval-researcher/mcp_server/sse.py)
- Implement an SSE generator that yields events from `graph.astream_events`.
- Format events as JSON data lines: `data: {...}\n\n`.

#### [MODIFY] [service/api.py](file:///c:/pyPractice/mcp-eval-researcher/service/api.py)
- Add `GET /research/stream` endpoint.
- Integrate with `GraphRuntime`.

### 2. Graph Runtime
#### [MODIFY] [graph/runtime.py](file:///c:/pyPractice/mcp-eval-researcher/graph/runtime.py)
- Ensure `stream_events` is exposed and context-aware.

### 3. Verification Plan
#### Automated Tests
- Create `tests/integration/test_streaming.py`.
- Verify events are received in correct order (start -> progress -> token -> end).

#### Manual Verification
- Use `curl` to consume the stream:
  ```bash
  curl -N "http://localhost:8080/research/stream?query=test"
  ```
