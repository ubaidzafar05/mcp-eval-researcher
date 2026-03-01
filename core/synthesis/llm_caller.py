"""core.synthesis.llm_caller — LLM provider abstraction for the synthesizer.

This module consolidates the complexity of talking to different LLM providers,
handling their specific request formats and response parsing.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def provider_kwargs(provider: str, model_name: str, system_msg: str, user_msg: str) -> dict[str, Any]:
    """Build provider-specific keyword arguments for the LLM client call."""
    if provider in {"openai", "groq", "openrouter"}:
        return {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        }
    if provider == "anthropic":
        return {
            "model": model_name,
            "max_tokens": 5200,
            "system": system_msg,
            "messages": [{"role": "user", "content": user_msg}],
        }
    # Default message format for generic providers
    return {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
    }


def generation_token_budget(*, deep_mode: bool) -> int:
    """Return the max_tokens value based on research depth."""
    return 6500 if deep_mode else 2800


def call_llm(
    client: Any,
    provider: str,
    model_name: str,
    system_msg: str,
    user_msg: str,
    *,
    deep_mode: bool,
) -> str:
    """Execute the LLM call and return the response content text.

    Consolidates the provider dispatch and response extraction logic.
    """
    kwargs = provider_kwargs(provider, model_name, system_msg, user_msg)
    # Use a default temperature if none provided by router
    temperature = 0.35

    try:
        if provider in {"openai", "groq", "openrouter"}:
            resp = client.chat.completions.create(
                **kwargs,
                max_tokens=generation_token_budget(deep_mode=deep_mode),
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""

        if provider == "anthropic":
            resp = client.messages.create(
                **kwargs,
                temperature=temperature,
            )
            return resp.content[0].text if resp.content else ""

        if provider == "huggingface":
            resp = client.chat_completion(
                **kwargs,
                max_tokens=3000 if deep_mode else 2200,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""

    except Exception as exc:
        logger.error("LLM call failed for provider %s: %s", provider, exc)
        raise exc

    return ""
