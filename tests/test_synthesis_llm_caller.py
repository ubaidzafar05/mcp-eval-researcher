"""Tests for core.synthesis.llm_caller — test-first."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.synthesis.llm_caller import (
    call_llm,
    generation_token_budget,
    provider_kwargs,
)


def test_provider_kwargs_openai():
    res = provider_kwargs("openai", "gpt-4", "sys", "user")
    assert res["model"] == "gpt-4"
    assert res["messages"][0]["role"] == "system"
    assert res["messages"][1]["content"] == "user"

def test_provider_kwargs_anthropic():
    res = provider_kwargs("anthropic", "claude-3", "sys", "user")
    assert res["model"] == "claude-3"
    assert res["system"] == "sys"
    assert res["messages"][0]["content"] == "user"

def test_generation_token_budget_deep():
    assert generation_token_budget(deep_mode=True) == 6500

def test_generation_token_budget_standard():
    assert generation_token_budget(deep_mode=False) == 2800

@pytest.mark.asyncio
async def test_call_llm_openai_mock():
    # call_llm is synchronous in current implementation (wraps client call)
    client = MagicMock()
    # Mock the return value for OpenAI-style client
    client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content="synthesis report"))]

    result = call_llm(client, "openai", "gpt-4", "sys", "user", deep_mode=False)
    assert result == "synthesis report"
    client.chat.completions.create.assert_called_once()

@pytest.mark.asyncio
async def test_call_llm_anthropic_mock():
    client = MagicMock()
    # Mock the return value for Anthropic-style client
    client.messages.create.return_value.content = [MagicMock(text="anthropic report")]

    result = call_llm(client, "anthropic", "claude-3", "sys", "user", deep_mode=True)
    assert result == "anthropic report"
    client.messages.create.assert_called_once()
