from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

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
    """Hybrid tracing: Local structured logs + Optional OpenTelemetry + LangSmith."""

    def __init__(self, config: RunConfig):
        self.config = config
        self.tracer = None
        
        # 1. LangSmith Setup
        if config.langsmith_api_key:
            os.environ.setdefault("LANGSMITH_API_KEY", config.langsmith_api_key)
            os.environ.setdefault("LANGSMITH_TRACING", "true")
            os.environ.setdefault("LANGSMITH_PROJECT", "cloud-hive")

        # 2. OpenTelemetry Setup
        if config.otel_enabled:
            resource = Resource.create({"service.name": "cloud-hive"})
            provider = TracerProvider(resource=resource)
            processor = BatchSpanProcessor(
                OTLPSpanExporter(endpoint=config.otel_endpoint, insecure=True)
            )
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            self.tracer = trace.get_tracer("cloud-hive")

    def event(
        self,
        run_id: str,
        node: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        payload = payload or {}
        
        # A. Structured Log
        record = {
            "run_id": run_id,
            "node": node,
            "message": message,
            "payload": payload,
        }
        logger.info(json.dumps(record))
        
        # B. OTEL Span
        if self.tracer:
            with self.tracer.start_as_current_span(node) as span:
                span.set_attribute("run_id", run_id)
                span.set_attribute("message", message)
                for k, v in payload.items():
                    if isinstance(v, (str, int, float, bool)):
                        span.set_attribute(k, v)
                    else:
                        span.set_attribute(k, str(v))
