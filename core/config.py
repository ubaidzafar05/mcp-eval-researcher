from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.models import RunConfig


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _ensure_dirs(config: RunConfig) -> None:
    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
    Path(config.logs_dir).mkdir(parents=True, exist_ok=True)
    Path(config.data_dir).mkdir(parents=True, exist_ok=True)
    Path(config.memory_dir).mkdir(parents=True, exist_ok=True)


def load_config(overrides: dict[str, Any] | None = None) -> RunConfig:
    load_dotenv(override=False)
    data: dict[str, Any] = {
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "judge_provider": os.getenv("JUDGE_PROVIDER", "groq"),
        "max_tasks": _env_int("MAX_TASKS", 3),
        "max_retries": _env_int("MAX_RETRIES", 3),
        "correction_loop_limit": _env_int("CORRECTION_LOOP_LIMIT", 1),
        "faithfulness_threshold": _env_float("FAITHFULNESS_THRESHOLD", 0.70),
        "relevancy_threshold": _env_float("RELEVANCY_THRESHOLD", 0.70),
        "citation_threshold": _env_float("CITATION_THRESHOLD", 0.85),
        "groq_rpm": _env_int("GROQ_RPM", 20),
        "tavily_rpm": _env_int("TAVILY_RPM", 5),
        "ddg_rpm": _env_int("DDG_RPM", 20),
        "firecrawl_rpm": _env_int("FIRECRAWL_RPM", 3),
        "judge_rpm": _env_int("JUDGE_RPM", 15),
        "per_doc_tokens": _env_int("PER_DOC_TOKENS", 500),
        "total_context_tokens": _env_int("TOTAL_CONTEXT_TOKENS", 1800),
        "output_dir": os.getenv("OUTPUT_DIR", "outputs"),
        "logs_dir": os.getenv("LOGS_DIR", "logs"),
        "data_dir": os.getenv("DATA_DIR", "data"),
        "memory_dir": os.getenv("MEMORY_DIR", "data/chroma"),
        "retention_days": _env_int("RETENTION_DAYS", 30),
        "hitl_mode": os.getenv("HITL_MODE", "on_low_confidence"),
        "interactive_hitl": _env_bool("INTERACTIVE_HITL", True),
        "groq_api_key": os.getenv("GROQ_API_KEY"),
        "tavily_api_key": os.getenv("TAVILY_API_KEY"),
        "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY"),
        "hf_token": os.getenv("HF_TOKEN"),
        "langsmith_api_key": os.getenv("LANGSMITH_API_KEY"),
        "deepeval_telemetry": os.getenv("DEEPEVAL_TELEMETRY", "off"),
        "mcp_mode": os.getenv("MCP_MODE", "auto"),
        "mcp_transport": os.getenv("MCP_TRANSPORT", "stdio"),
        "mcp_web_server_cmd": os.getenv(
            "MCP_WEB_SERVER_CMD", "python -m mcp_server.web_stdio_app"
        ),
        "mcp_local_server_cmd": os.getenv(
            "MCP_LOCAL_SERVER_CMD", "python -m mcp_server.local_stdio_app"
        ),
        "mcp_web_http_server_cmd": os.getenv(
            "MCP_WEB_HTTP_SERVER_CMD", "python -m mcp_server.web_streamable_http_app"
        ),
        "mcp_local_http_server_cmd": os.getenv(
            "MCP_LOCAL_HTTP_SERVER_CMD", "python -m mcp_server.local_streamable_http_app"
        ),
        "mcp_http_host": os.getenv("MCP_HTTP_HOST", "127.0.0.1"),
        "mcp_http_port_web": _env_int("MCP_HTTP_PORT_WEB", 8001),
        "mcp_http_port_local": _env_int("MCP_HTTP_PORT_LOCAL", 8002),
        "mcp_http_web_url": os.getenv("MCP_HTTP_WEB_URL"),
        "mcp_http_local_url": os.getenv("MCP_HTTP_LOCAL_URL"),
        "mcp_http_external": _env_bool("MCP_HTTP_EXTERNAL", False),
        "mcp_auth_token": os.getenv("MCP_AUTH_TOKEN"),
        "mcp_client_auth_token": os.getenv("MCP_CLIENT_AUTH_TOKEN"),
        "mcp_allow_insecure_http": _env_bool("MCP_ALLOW_INSECURE_HTTP", False),
        "mcp_allow_external_bind": _env_bool("MCP_ALLOW_EXTERNAL_BIND", False),
        "mcp_startup_timeout_seconds": _env_int("MCP_STARTUP_TIMEOUT_SECONDS", 20),
        "mcp_call_timeout_seconds": _env_int("MCP_CALL_TIMEOUT_SECONDS", 15),
        "metrics_enabled": _env_bool("METRICS_ENABLED", False),
        "metrics_host": os.getenv("METRICS_HOST", "127.0.0.1"),
        "metrics_port": _env_int("METRICS_PORT", 9010),
        "expected_github_owner": os.getenv("EXPECTED_GITHUB_OWNER", "UbaidZafar"),
    }
    if overrides:
        data.update(overrides)
    config = RunConfig(**data)
    _ensure_dirs(config)
    return config
