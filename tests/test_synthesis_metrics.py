"""Tests for core.synthesis.metrics — test-first."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.models import Citation, QueryProfile
from core.synthesis.metrics import (
    build_fallback_metrics,
    build_success_metrics,
    intent_note,
    merge_retrieval_stats,
    policy_note,
    source_mix,
)


@pytest.fixture
def mock_profile():
    profile = MagicMock(spec=QueryProfile)
    profile.intent_type = "explanatory"
    return profile

def test_source_mix_counts():
    citations = [
        Citation(claim_id="C1", source_url="url1", source_tier="A"),
        Citation(claim_id="C2", source_url="url2", source_tier="B"),
        Citation(claim_id="C3", source_url="url3", source_tier="C"),
        Citation(claim_id="C4", source_url="url4", source_tier="A"),
    ]
    res = source_mix(citations)
    assert res["tier_ab_count"] == 3
    assert res["tier_c_count"] == 1

def test_merge_retrieval_stats_sums_correctly():
    state = {
        "tavily_retrieval_stats": {"candidate_count": 10, "filtered_count": 2, "stale_count": 1},
        "ddg_retrieval_stats": {"candidate_count": 5, "filtered_count": 1, "stale_count": 0},
    }
    res = merge_retrieval_stats(state, kept_count=12)
    assert res["candidate_count"] == 15
    assert res["filtered_count"] == 3
    assert res["kept_count"] == 12
    assert res["stale_count"] == 1

def test_policy_note_strict():
    assert "strict defensive" in policy_note("strict_defensive").lower()

def test_intent_note_comparative(mock_profile):
    mock_profile.intent_type = "comparative"
    assert "comparison" in intent_note(mock_profile).lower()

def test_build_success_metrics_structure():
    citations = [Citation(claim_id="C1", source_url="u1", source_tier="A")]
    state = {"metrics": {"prior": 1}}
    res = build_success_metrics(
        state=state,
        citations=citations,
        min_claims_target=5,
        quality_retry_attempted=True,
        quality_retry_succeeded=False,
        provider_alerts=["alert1"]
    )
    assert res["quality_verdict"] == "verified"
    assert res["prior"] == 1
    assert res["quality_retry_attempted"] is True
    assert res["source_mix"]["tier_ab_count"] == 1

def test_build_fallback_metrics_structure():
    state = {"metrics": {"prior": 0}}
    citations = [Citation(claim_id="C1", source_url="u1", source_tier="C")]
    res = build_fallback_metrics(
        state=state,
        citations=citations,
        reason="failed quality",
        provider_alerts=[]
    )
    assert res["quality_verdict"] == "constrained"
    assert res["constrained_reason_codes"] == ["failed quality"]
