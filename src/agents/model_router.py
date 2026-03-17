"""model_router.py — Routes LLM requests across multiple local Ollama models."""
from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import dataclass
from typing import Literal

from core.models import RunConfig

ModelProvider = Literal["ollama"]
TaskType = Literal["planning", "research", "synthesis", "correction", "evaluation"]
ModelTier = Literal["fast", "primary", "deep"]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    provider: ModelProvider
    model_name: str
    temperature: float | None = None
    tier: ModelTier = "primary"
    confidence: float | None = None
    reason: str | None = None
    router_mode: str | None = None
    was_downgraded: bool = False

    # Backward compatibility: allow `provider, model = select_model(...)`.
    def __iter__(self):
        yield self.provider
        yield self.model_name


class ModelRouter:
    """Configurable router — selects fast/primary/deep Ollama models."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._primary_inflight = 0
        self._deep_inflight = 0

    @contextlib.contextmanager
    def use_tier(self, tier: ModelTier):
        with self._lock:
            if tier == "primary":
                self._primary_inflight += 1
            elif tier == "deep":
                self._deep_inflight += 1
        try:
            yield
        finally:
            with self._lock:
                if tier == "primary" and self._primary_inflight > 0:
                    self._primary_inflight -= 1
                elif tier == "deep" and self._deep_inflight > 0:
                    self._deep_inflight -= 1

    def _task_temperature(self, task_type: TaskType) -> float:
        task_temperature = {
            "planning": 0.2,
            "research": 0.2,
            "synthesis": 0.5,
            "correction": 0.2,
            "evaluation": 0.1,
        }
        return task_temperature.get(task_type, 0.2)

    def _tier_from_task(
        self,
        *,
        task_type: TaskType,
        context_size: int,
        plan_complexity: str | None,
    ) -> ModelTier:
        if task_type in {"planning", "research"}:
            return "fast" if context_size < 1000 else "primary"
        if task_type == "synthesis":
            if context_size >= self.config.router_max_context_deep or plan_complexity == "high":
                return "deep"
            return "primary"
        return "primary"

    def _parse_router_json(self, raw: str) -> dict:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()
        start = text.find("{")
        if start < 0:
            return {}
        depth = 0
        end = -1
        for idx, ch in enumerate(text[start:], start=start):  # type: ignore
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end < 0:
            return {}
        try:
            return json.loads(text[start : end + 1])  # type: ignore
        except json.JSONDecodeError:
            return {}

    def _llm_route(
        self,
        *,
        task_type: TaskType,
        context_size: int,
        latency_budget_ms: int,
        tenant_tier: str,
        plan_complexity: str | None,
    ) -> tuple[ModelTier, float | None, str | None]:
        from openai import OpenAI

        prompt = (
            "You are a routing classifier. Choose tier fast, primary, or deep.\n"
            "Return JSON with keys: tier, confidence (0-1), reason.\n"
            "Rules: fast for short/simple tasks; deep for long reasoning, audits, or high complexity.\n"
            f"task_type={task_type}\n"
            f"context_size={context_size}\n"
            f"latency_budget_ms={latency_budget_ms}\n"
            f"tenant_tier={tenant_tier}\n"
            f"plan_complexity={plan_complexity or 'unknown'}\n"
        )
        client = OpenAI(
            api_key="ollama",
            base_url=f"{self.config.ollama_endpoint}/v1",
            timeout=5,
        )
        try:
            resp = client.chat.completions.create(
                model=self.config.router_model,
                messages=[
                    {"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=200,
            )
            content = resp.choices[0].message.content or ""
        except Exception:
            return "primary", None, "router_error"

        data = self._parse_router_json(content)
        tier = str(data.get("tier", "primary")).strip().lower()
        confidence = data.get("confidence")
        reason = str(data.get("reason", "")).strip() if data.get("reason") else None
        if tier not in {"fast", "primary", "deep"}:
            return "primary", None, "router_invalid_tier"
        try:
            conf_val = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            conf_val = None
        from typing import cast

        tier_lit = cast(ModelTier, tier)
        return tier_lit, conf_val, reason

    def select_model(
        self,
        *,
        task_type: TaskType,
        context_size: int,
        latency_budget_ms: int,
        tenant_tier: str,
        tenant_context: object | None = None,
        **kwargs: object,
    ) -> ModelSelection:
        plan_complexity = str(kwargs.get("plan_complexity") or "").strip().lower() or None
        router_mode = self.config.router_mode
        tier: ModelTier = self._tier_from_task(
            task_type=task_type,
            context_size=context_size,
            plan_complexity=plan_complexity,
        )
        confidence: float | None = None
        reason: str | None = "heuristic"

        # 'heuristic' mode (default) skips the LLM routing call — the
        # deterministic tier selection above is sufficient and avoids an
        # extra Ollama round-trip that adds 5-10s to every pipeline run.
        if router_mode in {"llm", "hybrid"}:
            should_route = router_mode == "llm"
            if router_mode == "hybrid":
                should_route = task_type in {"synthesis", "correction", "evaluation"} or context_size >= 2000
            if should_route:
                llm_tier, llm_conf, llm_reason = self._llm_route(
                    task_type=task_type,
                    context_size=context_size,
                    latency_budget_ms=latency_budget_ms,
                    tenant_tier=tenant_tier,
                    plan_complexity=plan_complexity,
                )
                confidence = llm_conf
                reason = llm_reason or "router_llm"
                if task_type in {"correction", "evaluation"}:
                    if llm_tier == "deep" and (llm_conf or 0.0) >= self.config.router_escalation_threshold:
                        tier = "deep"
                    else:
                        tier = "primary"
                else:
                    tier = llm_tier

        was_downgraded = False
        if tier == "deep" and not self.config.router_allow_deep_parallel:
            with self._lock:
                if self._primary_inflight > 0:
                    tier = "primary"
                    was_downgraded = True

        if tier == "fast":
            model_name = self.config.ollama_model_fast
        elif tier == "deep":
            model_name = self.config.ollama_model_deep
        else:
            model_name = self.config.ollama_model_primary

        return ModelSelection(
            provider="ollama",
            model_name=model_name,
            temperature=self._task_temperature(task_type),
            tier=tier,
            confidence=confidence,
            reason=reason,
            router_mode=router_mode,
            was_downgraded=was_downgraded,
        )
