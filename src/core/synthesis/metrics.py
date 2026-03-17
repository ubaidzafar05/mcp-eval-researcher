"""core.synthesis.metrics — Helpers for building the synthesizer metrics dict.

This module consolidates the logic for aggregating telemetry, source mix stats,
and verification results into the standardized metrics envelope.
"""
from __future__ import annotations

from typing import Any

from core.citations import normalized_domain
from core.models import Citation, QueryProfile


def source_mix(citations: list[Citation]) -> dict[str, int]:
    """Return counts for tiers, domains, and providers in a citation list."""
    return {
        "tier_ab_count": sum(1 for c in citations if (c.source_tier or "").upper() in {"A", "B"}),
        "tier_c_count": sum(1 for c in citations if (c.source_tier or "").upper() == "C"),
        "domain_count": len(
            {normalized_domain(c.source_url) for c in citations if normalized_domain(c.source_url)}
        ),
        "provider_count": len(
            {(c.provider or "").strip().lower() for c in citations if (c.provider or "").strip()}
        ),
    }


def merge_retrieval_stats(state: Any, *, kept_count: int) -> dict[str, int]:
    """Aggregate candidate, filtered, and stale counts from retrieval lanes."""
    # Handle state either as a dict or an object with get()
    get_fn = state.get if hasattr(state, "get") else lambda k, d: state.get(k, d)

    lanes = (
        dict(get_fn("tavily_retrieval_stats", {})),
        dict(get_fn("ddg_retrieval_stats", {})),
        dict(get_fn("firecrawl_retrieval_stats", {})),
    )
    candidate_count = sum(int(lane.get("candidate_count", 0)) for lane in lanes)
    filtered_count = sum(int(lane.get("filtered_count", 0)) for lane in lanes)
    stale_count = sum(int(lane.get("stale_count", 0)) for lane in lanes)

    if candidate_count <= 0:
        candidate_count = kept_count
    if filtered_count <= 0:
        filtered_count = max(0, candidate_count - kept_count)

    return {
        "candidate_count": candidate_count,
        "filtered_count": filtered_count,
        "kept_count": kept_count,
        "stale_count": stale_count,
    }


def policy_note(policy: str) -> str:
    """Return a human-readable note explaining the applied safety policy."""
    if policy == "strict_defensive":
        return "This report applies strict defensive framing: no procedural bypass guidance is provided."
    if policy == "balanced_defensive":
        return "This report includes threat-pattern context while restricting actionable evasion steps."
    if policy == "defensive":
        return "This report emphasizes defensive controls, monitoring, and mitigation over bypass tactics."
    return "Standard analytical framing is applied."


def intent_note(query_profile: QueryProfile) -> str:
    """Return a human-readable note explaining the prioritized intent framing."""
    if query_profile.intent_type == "comparative":
        return "This report prioritizes side-by-side comparison criteria, tradeoff evaluation, and decision implications."
    if query_profile.intent_type == "operational":
        return "This report prioritizes operational constraints, implementation risks, and measurable controls."
    if query_profile.intent_type == "security_dual_use":
        return "This report prioritizes defensive risk framing, abuse prevention, and mitigation guidance."
    if query_profile.intent_type == "diagnostic":
        return "This report prioritizes diagnosis signals, likely root causes, and verification steps."
    return "This report prioritizes conceptual clarity, evidence reconciliation, and practical interpretation."


def build_success_metrics(
    *,
    state: Any,
    citations: list[Citation],
    min_claims_target: int,
    kept_count: int = 0,
    quality_retry_attempted: bool = False,
    quality_retry_succeeded: bool = False,
    provider_alerts: list[str] | None = None,
) -> dict[str, Any]:
    """Build the metrics dictionary for a successful synthesis run."""
    # Use existing metrics as base if available
    get_fn = state.get if hasattr(state, "get") else lambda k, d: state.get(k, d)
    base_metrics = dict(get_fn("metrics", {}))

    ab_count = sum(1 for c in citations if (c.source_tier or "").upper() in {"A", "B"})
    c_count = sum(1 for c in citations if (c.source_tier or "").upper() == "C")

    return {
        **base_metrics,
        "quality_retry_attempted": quality_retry_attempted,
        "quality_retry_succeeded": quality_retry_succeeded,
        "claim_mix": {
            "asserted": ab_count,
            "constrained": c_count,
            "withheld": max(0, min_claims_target - len(citations)),
        },
        "source_mix": source_mix(citations),
        "retrieval_stats": merge_retrieval_stats(state, kept_count=kept_count),
        "verification_stats": {
            "verified_count": ab_count,
            "constrained_count": c_count,
            "withheld_count": max(0, min_claims_target - len(citations)),
            "unmet_rules": 0,
        },
        "availability_stats": {"open_confirmed_count": 0, "unknown_count": 0},
        "quality_verdict": "verified",
        "provider_floor_met": True,
        "constrained_reason_codes": [],
        "provider_alerts": provider_alerts or [],
    }


def build_fallback_metrics(
    *,
    state: Any,
    citations: list[Citation],
    reason: str,
    kept_count: int = 0,
    provider_alerts: list[str] | None = None,
) -> dict[str, Any]:
    """Build the metrics dictionary for a fallback/constrained synthesis run."""
    get_fn = state.get if hasattr(state, "get") else lambda k, d: state.get(k, d)
    base_metrics = dict(get_fn("metrics", {}))

    mix = source_mix(citations)

    return {
        **base_metrics,
        "quality_verdict": "constrained",
        "constrained_reason_codes": [reason],
        "source_mix": mix,
        "retrieval_stats": merge_retrieval_stats(state, kept_count=kept_count),
        "provider_alerts": provider_alerts or [],
    }
