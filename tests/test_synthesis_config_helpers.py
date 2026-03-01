"""Tests for core.synthesis.config_helpers — test-first."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.synthesis.config_helpers import (
    adaptive_min_external_sources,
    effective_max_ctier_ratio,
    effective_min_ab_sources,
    effective_min_claims,
    effective_min_unique_domains,
    effective_min_words,
    effective_source_quality_bar,
)


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.config.research_mode = "deep"
    runtime.config.target_report_words_peak_min = 1500
    runtime.config.min_report_words_deep = 1000
    runtime.config.min_claims_deep = 10
    runtime.config.min_primary_claims = 15
    runtime.config.primary_source_policy = "strict"
    runtime.config.min_tier_ab_sources = 3
    runtime.config.min_ab_sources = 5
    runtime.config.min_unique_domains = 4
    runtime.config.max_ctier_claim_ratio = 0.2
    return runtime

def test_adaptive_min_external_sources_uses_configured_when_available():
    assert adaptive_min_external_sources(available_sources=10, configured_min=5, allow_relax=False) == 5

def test_adaptive_min_external_sources_relaxes_when_allowed():
    assert adaptive_min_external_sources(available_sources=3, configured_min=5, allow_relax=True) == 2

def test_adaptive_min_external_sources_does_not_relax_when_disallowed():
    assert adaptive_min_external_sources(available_sources=3, configured_min=5, allow_relax=False) == 5

def test_effective_min_words_peak(mock_runtime):
    mock_runtime.config.research_mode = "peak"
    assert effective_min_words(mock_runtime, deep_mode=True) == 1500

def test_effective_min_words_deep(mock_runtime):
    mock_runtime.config.research_mode = "deep"
    assert effective_min_words(mock_runtime, deep_mode=True) == 1000

def test_effective_min_words_fallback(mock_runtime):
    mock_runtime.config.research_mode = "standard"
    assert effective_min_words(mock_runtime, deep_mode=False) == 450

def test_effective_min_claims_peak(mock_runtime):
    mock_runtime.config.research_mode = "peak"
    assert effective_min_claims(mock_runtime, deep_mode=True) == 15

def test_effective_min_claims_deep(mock_runtime):
    mock_runtime.config.research_mode = "deep"
    assert effective_min_claims(mock_runtime, deep_mode=True) == 10

def test_effective_min_ab_sources_strict(mock_runtime):
    mock_runtime.config.primary_source_policy = "strict"
    assert effective_min_ab_sources(mock_runtime) == 5

def test_effective_min_unique_domains_strict(mock_runtime):
    mock_runtime.config.primary_source_policy = "strict"
    assert effective_min_unique_domains(mock_runtime) == 4

def test_effective_max_ctier_ratio_strict(mock_runtime):
    mock_runtime.config.primary_source_policy = "strict"
    assert effective_max_ctier_ratio(mock_runtime) == 0.2

def test_effective_source_quality_bar_strict(mock_runtime):
    mock_runtime.config.primary_source_policy = "strict"
    assert effective_source_quality_bar(mock_runtime) == "high_confidence"

def test_effective_source_quality_bar_hybrid(mock_runtime):
    mock_runtime.config.primary_source_policy = "hybrid"
    assert effective_source_quality_bar(mock_runtime) == "mixed"
