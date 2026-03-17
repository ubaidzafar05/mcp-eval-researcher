"""test_synthesis_llm_caller.py — Tests for the Ollama-only LLM caller."""
from unittest.mock import MagicMock

from core.synthesis.llm_caller import call_llm, generation_token_budget


def test_generation_token_budget_deep():
    assert generation_token_budget(deep_mode=True) == 6500


def test_generation_token_budget_fast():
    assert generation_token_budget(deep_mode=False) == 2800


def test_call_llm_returns_content():
    """call_llm should call client.chat.completions.create and return content."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="test response"))]
    )
    result = call_llm(
        mock_client,
        "ollama",
        "qwen3:8b",
        "system prompt",
        "user prompt",
        deep_mode=True,
    )
    assert result == "test response"
    mock_client.chat.completions.create.assert_called_once()
