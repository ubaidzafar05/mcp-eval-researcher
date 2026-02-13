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
        memory_store = ChromaMemoryStore(cfg.memory_dir)
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
        if self.config.metrics_enabled:
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

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_llm_client(self, provider: str):
        if provider == "openai":
            from openai import OpenAI
            return OpenAI(api_key=self.config.openai_api_key)
        elif provider == "anthropic":
            from anthropic import Anthropic
            return Anthropic(api_key=self.config.anthropic_api_key)
        elif provider == "groq":
            from groq import Groq
            return Groq(api_key=self.config.groq_api_key)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
