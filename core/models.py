from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class TaskSpec(BaseModel):
    id: int
    title: str
    search_query: str
    tool_hint: Literal["tavily", "ddg", "firecrawl", "any"] = "any"
    priority: int = 1
    firecrawl_needed: bool = False


class RetrievedDoc(BaseModel):
    provider: Literal["tavily", "ddg", "firecrawl", "memory", "fallback"]
    title: str
    url: str = ""
    snippet: str = ""
    content: str = ""
    score: float = 0.0
    retrieved_at: str = Field(default_factory=utc_now_iso)
    meta: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    claim_id: str
    source_url: str
    title: str = ""
    provider: str = ""
    evidence: str = ""


class EvalResult(BaseModel):
    faithfulness: float = 0.0
    relevancy: float = 0.0
    citation_coverage: float = 0.0
    pass_gate: bool = False
    reasons: list[str] = Field(default_factory=list)


class RunConfig(BaseModel):
    groq_model: str = "llama-3.3-70b-versatile"
    judge_provider: Literal["groq", "hf", "stub"] = "groq"
    max_tasks: int = 3
    max_retries: int = 3
    correction_loop_limit: int = 1
    faithfulness_threshold: float = 0.70
    relevancy_threshold: float = 0.70
    citation_threshold: float = 0.85
    groq_rpm: int = 20
    tavily_rpm: int = 5
    ddg_rpm: int = 20
    firecrawl_rpm: int = 3
    judge_rpm: int = 15
    per_doc_tokens: int = 500
    total_context_tokens: int = 1800
    output_dir: str = "outputs"
    logs_dir: str = "logs"
    data_dir: str = "data"
    memory_dir: str = "data/chroma"
    retention_days: int = 30
    hitl_mode: Literal["on_low_confidence", "always", "never"] = "on_low_confidence"
    interactive_hitl: bool = True
    groq_api_key: str | None = None
    tavily_api_key: str | None = None
    firecrawl_api_key: str | None = None
    hf_token: str | None = None
    langsmith_api_key: str | None = None
    deepeval_telemetry: str = "off"
    mcp_mode: Literal["transport", "inprocess", "auto"] = "auto"
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_web_server_cmd: str = "python -m mcp_server.web_stdio_app"
    mcp_local_server_cmd: str = "python -m mcp_server.local_stdio_app"
    mcp_web_http_server_cmd: str = "python -m mcp_server.web_streamable_http_app"
    mcp_local_http_server_cmd: str = "python -m mcp_server.local_streamable_http_app"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port_web: int = 8001
    mcp_http_port_local: int = 8002
    mcp_http_web_url: str | None = None
    mcp_http_local_url: str | None = None
    mcp_http_external: bool = False
    mcp_auth_token: str | None = None
    mcp_client_auth_token: str | None = None
    mcp_allow_insecure_http: bool = False
    mcp_allow_external_bind: bool = False
    mcp_startup_timeout_seconds: int = 20
    mcp_call_timeout_seconds: int = 15
    metrics_enabled: bool = False
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9010
    expected_github_owner: str = "UbaidZafar"


class ResearchResult(BaseModel):
    run_id: str
    query: str
    final_report: str
    citations: list[Citation] = Field(default_factory=list)
    eval_result: EvalResult
    low_confidence: bool = False
    status: str = "completed"
    artifacts_path: str = ""
