from __future__ import annotations

from core.config import load_config
from evals.judges.llm_judge import judge_with_llm


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class _ChatCompletions:
    def __init__(self, payloads: list[str]):
        self._payloads = payloads
        self._calls = 0

    def create(self, **kwargs):  # noqa: ANN003
        del kwargs
        idx = min(self._calls, len(self._payloads) - 1)
        self._calls += 1
        return _Response(self._payloads[idx])


class _Chat:
    def __init__(self, payloads: list[str]):
        self.completions = _ChatCompletions(payloads)


class _Client:
    def __init__(self, payloads: list[str]):
        self.chat = _Chat(payloads)


def test_llm_judge_parses_fenced_json_payload() -> None:
    cfg = load_config({"judge_json_mode": "repair_retry_fallback", "interactive_hitl": False})
    client = _Client(
        [
            "```json\n"
            '{"faithfulness": 0.91, "relevancy": 0.86, "reasons": ["ok"]}\n'
            "```",
        ]
    )
    result = judge_with_llm(
        query="test query",
        report="Report body [C1].",
        citations=[],
        citation_coverage=0.9,
        config=cfg,
        client=client,
        provider="openai",
        model="dummy",
    )
    assert result.faithfulness == 0.91
    assert result.relevancy == 0.86
    assert result.meta.get("judge_fallback_used") is False


def test_llm_judge_retries_then_falls_back_when_payload_is_invalid() -> None:
    cfg = load_config({"judge_json_mode": "repair_retry_fallback", "interactive_hitl": False})
    client = _Client(["not-json", "still-not-json"])
    result = judge_with_llm(
        query="test query",
        report="Report body [C1].",
        citations=[],
        citation_coverage=0.9,
        config=cfg,
        client=client,
        provider="openai",
        model="dummy",
    )
    assert result.meta.get("judge_fallback_used") is True
    assert result.meta.get("judge_retry_used") is True
    assert any("deterministic fallback" in reason.lower() for reason in result.reasons)

