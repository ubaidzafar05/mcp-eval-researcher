"""core.synthesis.llm_caller — LLM call abstraction for the synthesizer.

All calls go through the OpenAI-compatible chat completions API,
which is how Ollama exposes its ``/v1`` endpoint.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Legacy fallback — prefer token_budget_for_task() from config.py instead.
_DEFAULT_TOKEN_BUDGET = 4096


def generation_token_budget(*, deep_mode: bool) -> int:
    """Legacy helper — returns the default token budget.

    Callers should prefer ``token_budget_for_task(config, task)`` which
    scales with the user-selected report_length.
    """
    return _DEFAULT_TOKEN_BUDGET if deep_mode else _DEFAULT_TOKEN_BUDGET


def _needs_no_think(model_name: str) -> bool:
    """Return True for models that default to chain-of-thought thinking mode.

    qwen3 and deepseek-r1 generate verbose internal reasoning tokens before
    responding, inflating latency by 3-10x. Adding /no_think to the prompt
    or using a chat_template flag suppresses this.
    """
    lower = (model_name or "").lower()
    return "qwen3" in lower or "deepseek-r1" in lower


def call_llm(
    client: Any,
    provider: str,
    model_name: str,
    system_msg: str,
    user_msg: str,
    *,
    deep_mode: bool,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> str:
    """Execute the LLM call via the OpenAI-compatible chat completions API.

    Parameters
    ----------
    max_tokens : int | None
        Override the default token budget.  When ``None`` falls back to
        ``generation_token_budget()``.
    timeout : float | None
        Per-request timeout in seconds.  Defaults to 600s.
    """
    del provider  # always Ollama — kept for backward compat
    temperature = 0.35
    effective_max_tokens = max_tokens or generation_token_budget(deep_mode=deep_mode)
    effective_timeout = timeout or 600.0

    # Suppress chain-of-thought on reasoning models to avoid 3-minute+ latency.
    effective_system_msg = system_msg
    if _needs_no_think(model_name):
        effective_system_msg = "/no_think\n" + system_msg

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": effective_system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=effective_max_tokens,
            temperature=temperature,
            timeout=effective_timeout,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        raise
