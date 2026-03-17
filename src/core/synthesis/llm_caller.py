"""core.synthesis.llm_caller — LLM call abstraction for the synthesizer.

All calls go through the OpenAI-compatible chat completions API,
which is how Ollama exposes its ``/v1`` endpoint.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generation_token_budget(*, deep_mode: bool) -> int:
    """Return the max_tokens value based on research depth."""
    return 16000 if deep_mode else 8000


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
) -> str:
    """Execute the LLM call via the OpenAI-compatible chat completions API.

    Ollama exposes an OpenAI-compatible ``/v1`` endpoint, so this is the
    universal call path for all synthesis operations.
    """
    del provider  # always Ollama — kept for backward compat
    temperature = 0.35

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
            max_tokens=generation_token_budget(deep_mode=deep_mode),
            temperature=temperature,
            timeout=300.0,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        raise
