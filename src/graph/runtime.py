"""runtime.py — Manages the graph execution runtime.

The LLM client factory now exclusively returns an OpenAI-compatible client
pointed at the local Ollama server's ``/v1`` endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.model_router import ModelRouter
from core.config import load_config
from core.metrics import ensure_metrics_server
from core.models import RunConfig
from core.observability import TraceManager, configure_logger
from mcp_server.client import MultiServerClient
from memory.chroma_store import ChromaMemoryStore


@dataclass(slots=True)
class GraphRuntime:
    config: RunConfig
    mcp_client: MultiServerClient
    memory_store: ChromaMemoryStore
    tracer: TraceManager
    model_router: ModelRouter
    started: bool = False

    @classmethod
    def from_config(cls, config: RunConfig | None = None) -> GraphRuntime:
        cfg = config or load_config()
        configure_logger(cfg)
        mcp_client = MultiServerClient.from_config(cfg)
        memory_store = ChromaMemoryStore(
            cfg.memory_dir,
            ollama_endpoint=cfg.ollama_endpoint,
            ollama_model_embed=cfg.ollama_model_embed,
        )
        tracer = TraceManager(cfg)
        model_router = ModelRouter(cfg)
        return cls(
            config=cfg,
            mcp_client=mcp_client,
            memory_store=memory_store,
            tracer=tracer,
            model_router=model_router,
        )

    def start(self) -> None:
        if self.started:
            return
        if self.config.enable_observability and self.config.metrics_enabled:
            ensure_metrics_server(self.config.metrics_host, self.config.metrics_port)
        probe = self.mcp_client.startup_probe()
        if self.config.mcp_mode == "transport" and not probe.transport_active:
            reason = probe.fallback_reason or "transport startup probe failed"
            raise RuntimeError(f"MCP transport startup failed in strict mode: {reason}")
        self.started = True

    def close(self) -> None:
        if not self.started:
            return
        self.mcp_client.close()
        self.started = False

    def __enter__(self) -> GraphRuntime:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def get_llm_client(self, provider: str, *, request_timeout_seconds: int | None = None):
        """Return an OpenAI-compatible client pointing at the local Ollama server.

        Ollama exposes an OpenAI-compatible ``/v1`` API, so we use the
        lightweight ``openai`` SDK as the universal transport layer.  The
        ``api_key`` is set to a placeholder value (Ollama ignores it).
        """
        del provider  # always Ollama — kept in signature for backward compat
        timeout = request_timeout_seconds if request_timeout_seconds and request_timeout_seconds > 0 else None
        from openai import OpenAI

        return OpenAI(
            api_key="ollama",  # Ollama ignores API keys but the SDK requires one
            base_url=f"{self.config.ollama_endpoint}/v1",
            timeout=timeout,
        )
