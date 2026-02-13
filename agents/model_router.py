from __future__ import annotations

from typing import Literal

from core.models import RunConfig

ModelProvider = Literal["anthropic", "openai", "groq", "local"]
TaskType = Literal["synthesis", "correction", "evaluation", "planning"]


class ModelRouter:
    def __init__(self, config: RunConfig):
        self.config = config

    def select_model(
        self,
        *,
        task_type: TaskType,
        context_size: int,
        latency_budget_ms: int,
        tenant_tier: str,
    ) -> tuple[ModelProvider, str]:
        strategy = self.config.model_routing_strategy

        if self.config.enable_local_llm and strategy == "cost_optimized":
            return "local", "local-default"

        if task_type == "evaluation" and latency_budget_ms < 1200:
            return "groq", "llama-3.3-70b-versatile"

        if tenant_tier == "enterprise" and task_type == "synthesis":
            return "anthropic", "claude-opus-4"

        if context_size > 100_000:
            return "anthropic", "claude-sonnet-4"

        if strategy == "latency_optimized":
            return "groq", "llama-3.3-70b-versatile"

        if task_type == "correction":
            return "openai", "gpt-4-turbo"

        return "groq", self.config.groq_model
