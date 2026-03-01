"""core.synthesis.config_helpers — Pure functions to compute effective config thresholds.

These helpers centralize the logic for deriving dynamic research targets (word counts,
claim targets, quality bars) from GraphRuntime config and current research mode.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graph.runtime import GraphRuntime


def adaptive_min_external_sources(
    available_sources: int,
    configured_min: int,
    *,
    allow_relax: bool,
) -> int:
    """Return the effective minimum external sources required.

    Relaxes to 2 if allow_relax is True and enough sources exist.
    """
    if available_sources >= configured_min:
        return configured_min
    if allow_relax and available_sources >= 2:
        return 2
    return configured_min


def effective_min_words(runtime: GraphRuntime, *, deep_mode: bool) -> int:
    """Compute report minimum word target based on research mode."""
    if runtime.config.research_mode == "peak":
        return runtime.config.target_report_words_peak_min
    if deep_mode:
        return runtime.config.min_report_words_deep
    return 450


def effective_min_claims(runtime: GraphRuntime, *, deep_mode: bool) -> int:
    """Compute report minimum claim target based on research mode."""
    if runtime.config.research_mode == "peak":
        return max(runtime.config.min_claims_deep, runtime.config.min_primary_claims)
    if deep_mode:
        return runtime.config.min_claims_deep
    return 4


def effective_min_ab_sources(runtime: GraphRuntime) -> int:
    """Compute effective minimum A/B tier sources target."""
    if runtime.config.primary_source_policy == "strict":
        return max(runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources)
    return runtime.config.min_tier_ab_sources


def effective_min_unique_domains(runtime: GraphRuntime) -> int:
    """Compute effective minimum unique domain target."""
    if runtime.config.primary_source_policy == "strict":
        return runtime.config.min_unique_domains
    return 0


def effective_max_ctier_ratio(runtime: GraphRuntime) -> float:
    """Compute maximum allowed ratio of Tier C claims."""
    if runtime.config.primary_source_policy == "strict":
        return runtime.config.max_ctier_claim_ratio
    return 1.0


def effective_source_quality_bar(runtime: GraphRuntime) -> str:
    """Compute source quality prioritization bar."""
    if runtime.config.primary_source_policy == "strict":
        return "high_confidence"
    if runtime.config.primary_source_policy == "hybrid":
        return "mixed"
    return "broad"
