from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Literal, cast

from core.models import RunConfig

ModelProvider = Literal[
    "anthropic",
    "openai",
    "groq",
    "openrouter",
    "huggingface",
    "local",
]
TaskType = Literal["planning", "research", "synthesis", "correction", "evaluation"]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    provider: ModelProvider
    model_name: str
    temperature: float | None = None

    # Backward compatibility: allow `provider, model = select_model(...)`.
    def __iter__(self):
        yield self.provider
        yield self.model_name


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
        tenant_context: Any | None = None,
        **kwargs,
    ) -> ModelSelection:
        del context_size, latency_budget_ms, tenant_context, kwargs  # reserved for future routing logic
        strategy = self.config.model_routing_strategy

        task_temperature = {
            "planning": 0.2,
            "research": 0.2,
            "synthesis": 0.5,
            "correction": 0.2,
            "evaluation": 0.1,
        }

        def pick(provider: ModelProvider, model_name: str) -> ModelSelection:
            return ModelSelection(
                provider=provider,
                model_name=model_name,
                temperature=task_temperature[task_type],
            )

        override_map = {
            "planning": self.config.planner_model,
            "research": self.config.researcher_model,
            "synthesis": self.config.synthesizer_model,
            "evaluation": self.config.evaluator_model,
            "correction": None,
        }

        if override := override_map.get(task_type):
            try:
                provider, model_name = override.split(":", 1)
                valid_providers = {
                    "anthropic",
                    "openai",
                    "groq",
                    "openrouter",
                    "huggingface",
                    "local",
                }
                if provider in valid_providers:
                    return pick(cast(ModelProvider, provider), model_name)
            except ValueError:
                pass

        has_hf_sdk = find_spec("huggingface_hub") is not None
        has_anthropic = bool(self.config.anthropic_api_key and self.config.anthropic_api_key.strip())
        has_openai = bool(self.config.openai_api_key and self.config.openai_api_key.strip())
        has_groq = bool(self.config.groq_api_key and self.config.groq_api_key.strip())
        has_openrouter = bool(self.config.openrouter_api_key and self.config.openrouter_api_key.strip())
        has_hf = bool(self.config.hf_token and self.config.hf_token.strip() and has_hf_sdk)
        pref = self.config.preferred_free_provider

        if tenant_tier == "enterprise":
            if task_type == "synthesis" and has_anthropic:
                return pick("anthropic", "claude-opus-4")
            if task_type == "planning" and has_openai:
                return pick("openai", "gpt-4-turbo")

        if strategy == "latency_optimized" and has_groq:
            return pick("groq", self.config.groq_model)

        if strategy == "cost_optimized" and self.config.enable_local_llm:
            return pick("local", "local-default")

        # Honor explicit free-provider preference when strategic routing does not force a choice.
        if pref == "huggingface" and has_hf:
            return pick("huggingface", self.config.huggingface_model)
        if pref == "openrouter" and has_openrouter:
            return pick("openrouter", self.config.openrouter_model)
        if pref == "groq" and has_groq:
            return pick("groq", self.config.groq_model)

        if task_type == "planning":
            if has_groq:
                return pick("groq", self.config.groq_model)
            if has_openrouter:
                return pick("openrouter", self.config.openrouter_model)

        if task_type in {"research", "evaluation"}:
            if has_groq:
                return pick("groq", self.config.groq_model)
            if has_openrouter:
                return pick("openrouter", self.config.openrouter_model)

        if task_type == "synthesis":
            if has_openrouter:
                return pick("openrouter", self.config.openrouter_model)
            if has_anthropic:
                return pick("anthropic", "claude-sonnet-4")
            if has_groq:
                return pick("groq", self.config.groq_model)

        if task_type == "correction":
            if has_openai:
                return pick("openai", "gpt-4-turbo")
            if has_groq:
                return pick("groq", self.config.groq_model)

        fallback_keys = {
            "groq": has_groq,
            "openrouter": has_openrouter,
            "huggingface": has_hf,
        }

        if fallback_keys.get(pref):
            if pref == "groq":
                return pick("groq", self.config.groq_model)
            if pref == "openrouter":
                return pick("openrouter", self.config.openrouter_model)
            if pref == "huggingface":
                return pick("huggingface", self.config.huggingface_model)

        if has_groq:
            return pick("groq", self.config.groq_model)
        if has_openrouter:
            return pick("openrouter", self.config.openrouter_model)
        if has_hf:
            return pick("huggingface", self.config.huggingface_model)

        return pick("groq", self.config.groq_model)
