from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from core.config import load_config
from main import run_research

app = FastAPI(title="Cloud Hive API", version="0.1.0")


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mcp_mode: str | None = None
    mcp_transport: str | None = None
    judge_provider: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.post("/research")
def research(request: ResearchRequest) -> dict:
    overrides = {"interactive_hitl": False}
    if request.mcp_mode:
        overrides["mcp_mode"] = request.mcp_mode
    if request.mcp_transport:
        overrides["mcp_transport"] = request.mcp_transport
    if request.judge_provider:
        overrides["judge_provider"] = request.judge_provider
    config = load_config(overrides)
    result = run_research(request.query, config=config)
    return result.model_dump(mode="json")


def main() -> None:
    import uvicorn

    uvicorn.run("service.api:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()

