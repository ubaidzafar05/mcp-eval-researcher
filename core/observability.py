from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from core.models import RunConfig


def configure_logger(config: RunConfig) -> None:
    Path(config.logs_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        Path(config.logs_dir) / "cloud_hive.log",
        serialize=True,
        level="INFO",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


class TraceManager:
    """Local-first tracing with optional LangSmith environment activation."""

    def __init__(self, config: RunConfig):
        self.config = config
        if config.langsmith_api_key:
            os.environ.setdefault("LANGSMITH_API_KEY", config.langsmith_api_key)
            os.environ.setdefault("LANGSMITH_TRACING", "true")
            os.environ.setdefault("LANGSMITH_PROJECT", "cloud-hive")

    def event(
        self,
        run_id: str,
        node: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "run_id": run_id,
            "node": node,
            "message": message,
            "payload": payload or {},
        }
        logger.info(json.dumps(record))

