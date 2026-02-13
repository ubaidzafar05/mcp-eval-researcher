from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from core.config import load_config
from core.models import ResearchUpdate
from main import run_research

app = FastAPI(title="Cloud Hive API", version="0.1.0")


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mcp_mode: str | None = None
    mcp_transport: str | None = None
    judge_provider: str | None = None
    tenant_id: str = "default"
    tenant_org_id: str = "default-org"
    tenant_user_id: str = "default-user"
    tenant_quota_tier: str = "free"


def _request_overrides(request: ResearchRequest) -> dict:
    overrides: dict[str, object] = {
        "interactive_hitl": False,
        "tenant_id": request.tenant_id,
        "tenant_org_id": request.tenant_org_id,
        "tenant_user_id": request.tenant_user_id,
        "tenant_quota_tier": request.tenant_quota_tier,
    }
    if request.mcp_mode:
        overrides["mcp_mode"] = request.mcp_mode
    if request.mcp_transport:
        overrides["mcp_transport"] = request.mcp_transport
    if request.judge_provider:
        overrides["judge_provider"] = request.judge_provider
    return overrides


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.post("/research")
def research(request: ResearchRequest) -> dict:
    overrides = _request_overrides(request)
    config = load_config(overrides)
    result = run_research(request.query, config=config)
    return result.model_dump(mode="json")


@app.post("/research/stream")
async def research_stream(request: ResearchRequest) -> StreamingResponse:
    async def event_generator():
        accepted = ResearchUpdate(
            stage="accepted",
            data={"query": request.query, "tenant_id": request.tenant_id},
        )
        yield f"data: {accepted.model_dump_json()}\n\n"

        planning = ResearchUpdate(stage="planning", data={"status": "planning_started"})
        yield f"data: {planning.model_dump_json()}\n\n"

        try:
            overrides = _request_overrides(request)
            config = load_config(overrides)
            result = await asyncio.to_thread(run_research, request.query, config=config)
            final = ResearchUpdate(
                stage="final",
                data={"result": result.model_dump(mode="json")},
            )
            yield f"data: {json.dumps(final.model_dump(mode='json'))}\n\n"
        except Exception as exc:  # noqa: BLE001
            failure = ResearchUpdate(stage="error", data={"message": str(exc)})
            yield f"data: {failure.model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def main() -> None:
    import uvicorn

    uvicorn.run("service.api:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
