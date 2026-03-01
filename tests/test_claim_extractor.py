"""Test suite for the two-pass LLM claim extraction and synthesis pipeline.

Tests claim extraction validation, JSON parsing, grouping, and the
analytical fallback generator — all without hitting real LLM APIs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.claim_extractor import (
    ExtractedClaim,
    _build_source_block,
    _safe_json_parse,
    _validate_claims,
    extract_claims,
    group_claims_by_topic,
)
from core.models import RetrievedDoc

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_doc(title: str, snippet: str, url: str = "https://example.com") -> RetrievedDoc:
    return RetrievedDoc(
        provider="tavily",
        title=title,
        url=url,
        snippet=snippet,
        score=0.8,
    )


SAMPLE_DOCS = [
    _make_doc("Performance study", "Model X achieves 95% accuracy on ImageNet.", "https://a.com/1"),
    _make_doc("Security audit", "The framework has 3 known CVEs in 2025.", "https://b.com/2"),
    _make_doc("Adoption trends", "Enterprise adoption grew 40% year-over-year.", "https://c.com/3"),
]

VALID_LLM_RESPONSE = json.dumps({
    "claims": [
        {
            "source_id": "C1",
            "topic": "performance",
            "assertion": "Model X achieves 95% accuracy on ImageNet benchmark data.",
            "evidence": "Model X achieves 95% accuracy on ImageNet.",
            "strength": "strong",
            "source_title": "Performance study",
            "source_url": "https://a.com/1",
        },
        {
            "source_id": "C2",
            "topic": "security",
            "assertion": "The framework has three known CVEs disclosed in 2025.",
            "evidence": "The framework has 3 known CVEs in 2025.",
            "strength": "strong",
            "source_title": "Security audit",
            "source_url": "https://b.com/2",
        },
        {
            "source_id": "C3",
            "topic": "adoption",
            "assertion": "Enterprise adoption of the framework grew 40% year-over-year.",
            "evidence": "Enterprise adoption grew 40% year-over-year.",
            "strength": "moderate",
            "source_title": "Adoption trends",
            "source_url": "https://c.com/3",
        },
    ]
})


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

def test_safe_json_parse_plain():
    """_safe_json_parse handles plain JSON."""
    data = _safe_json_parse('{"claims": []}')
    assert data == {"claims": []}
    print("  PASS test_safe_json_parse_plain")


def test_safe_json_parse_with_fences():
    """_safe_json_parse strips markdown code fences."""
    raw = '```json\n{"claims": [{"x": 1}]}\n```'
    data = _safe_json_parse(raw)
    assert "claims" in data
    print("  PASS test_safe_json_parse_with_fences")


def test_safe_json_parse_with_preamble():
    """_safe_json_parse handles text before the JSON object."""
    raw = 'Here is the result:\n{"claims": []}'
    data = _safe_json_parse(raw)
    assert data == {"claims": []}
    print("  PASS test_safe_json_parse_with_preamble")


def test_safe_json_parse_empty():
    """_safe_json_parse raises on empty input."""
    try:
        _safe_json_parse("")
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "empty" in str(e)
    print("  PASS test_safe_json_parse_empty")


def test_validate_claims_filters_short():
    """_validate_claims skips assertions shorter than 10 chars."""
    raw = [
        {"source_id": "C1", "assertion": "Short", "topic": "x", "evidence": "e", "strength": "moderate"},
        {"source_id": "C2", "assertion": "This is a proper assertion about something.", "topic": "y", "evidence": "e", "strength": "strong"},
    ]
    result = _validate_claims(raw, 2)
    assert len(result) == 1
    assert result[0].source_id == "C2"
    print("  PASS test_validate_claims_filters_short")


def test_validate_claims_deduplicates():
    """_validate_claims removes duplicate assertions."""
    raw = [
        {"source_id": "C1", "assertion": "The sky is blue and vast.", "topic": "x", "evidence": "e", "strength": "strong"},
        {"source_id": "C2", "assertion": "The sky is blue and vast.", "topic": "x", "evidence": "e", "strength": "strong"},
    ]
    result = _validate_claims(raw, 2)
    assert len(result) == 1
    print("  PASS test_validate_claims_deduplicates")


def test_validate_claims_normalizes_strength():
    """_validate_claims defaults invalid strength to 'moderate'."""
    raw = [
        {"source_id": "C1", "assertion": "Some valid assertion text here.", "topic": "x", "evidence": "e", "strength": "VERY_HIGH"},
    ]
    result = _validate_claims(raw, 1)
    assert result[0].strength == "moderate"
    print("  PASS test_validate_claims_normalizes_strength")


def test_build_source_block():
    """_build_source_block formats docs into numbered text."""
    block = _build_source_block(SAMPLE_DOCS)
    assert "[C1]" in block
    assert "[C2]" in block
    assert "[C3]" in block
    assert "Performance study" in block
    print("  PASS test_build_source_block")


def test_extract_claims_with_mock_groq():
    """extract_claims works with a mocked Groq-style client."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = VALID_LLM_RESPONSE
    mock_client.chat.completions.create.return_value = mock_response

    result = extract_claims(SAMPLE_DOCS, mock_client, "groq", "llama-3.1-8b-instant")

    assert result.error is None
    assert len(result.claims) == 3
    assert result.claims[0].topic == "performance"
    assert result.claims[1].topic == "security"
    assert result.claims[2].topic == "adoption"
    assert result.provider_used == "groq"
    print("  PASS test_extract_claims_with_mock_groq")


def test_extract_claims_empty_docs():
    """extract_claims returns error for empty doc list."""
    result = extract_claims([], MagicMock(), "groq", "test-model")
    assert result.error == "no_source_documents"
    print("  PASS test_extract_claims_empty_docs")


def test_extract_claims_llm_failure():
    """extract_claims handles LLM exceptions gracefully."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("API quota exceeded")

    result = extract_claims(SAMPLE_DOCS, mock_client, "groq", "test-model")
    assert result.error is not None
    assert "quota" in result.error.lower()
    print("  PASS test_extract_claims_llm_failure")


def test_group_claims_by_topic():
    """group_claims_by_topic groups claims correctly."""
    claims = [
        ExtractedClaim(source_id="C1", topic="Performance", assertion="Fast model.", evidence="e"),
        ExtractedClaim(source_id="C2", topic="Security", assertion="Has CVEs.", evidence="e"),
        ExtractedClaim(source_id="C3", topic="performance", assertion="Low latency.", evidence="e"),
    ]
    groups = group_claims_by_topic(claims)
    assert len(groups) == 2  # "performance" and "security"
    assert len(groups["performance"]) == 2
    assert len(groups["security"]) == 1
    print("  PASS test_group_claims_by_topic")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [
        test_safe_json_parse_plain,
        test_safe_json_parse_with_fences,
        test_safe_json_parse_with_preamble,
        test_safe_json_parse_empty,
        test_validate_claims_filters_short,
        test_validate_claims_deduplicates,
        test_validate_claims_normalizes_strength,
        test_build_source_block,
        test_extract_claims_with_mock_groq,
        test_extract_claims_empty_docs,
        test_extract_claims_llm_failure,
        test_group_claims_by_topic,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
