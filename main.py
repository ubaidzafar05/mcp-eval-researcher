from __future__ import annotations

import re
from collections.abc import Iterable
from time import perf_counter

from core.citations import normalized_domain
from core.config import load_config
from core.metrics import record_graph_run
from core.models import Citation, EvalResult, ResearchResult, RunConfig
from core.pruning import optional_dependency_status, startup_reason_codes
from core.report_quality import detect_placeholder_content
from core.retention import cleanup_old_artifacts
from core.run_registry import load_result_from_artifacts, upsert_registry_record
from core.runtime_profile import dependency_health
from core.source_quality import quality_stats
from graph.pipeline import run_graph
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _as_citations(values: Iterable[object]) -> list[Citation]:
    out: list[Citation] = []
    for value in values:
        if isinstance(value, Citation):
            out.append(value)
        else:
            out.append(Citation.model_validate(value))
    return out


def _default_hitl_input(state: ResearchState) -> str:
    from rich.prompt import Prompt

    return Prompt.ask(
        "Low-confidence output detected. Choose action",
        choices=["accept", "accept_with_warning", "retry", "abort"],
        default="accept_with_warning",
    )


def _report_meta(
    final_report: str,
    citations: list[Citation],
    eval_result: EvalResult,
    *,
    query: str,
    config: RunConfig,
    state_metrics: dict[str, object] | None = None,
    strict_high_confidence: bool = True,
    startup_profile: dict[str, object] | None = None,
) -> dict[str, object]:
    def _count_section_claims(section_name: str) -> int:
        match = re.search(
            rf"(?ims)^##\s+{re.escape(section_name)}\s*(.+?)(?=^##\s+|\Z)",
            final_report or "",
        )
        if not match:
            return 0
        return len(re.findall(r"\[C\d+\]", match.group(1)))

    def _count_direct_answer_bucket(label: str) -> int:
        match = re.search(
            r"(?ims)^##\s+Direct Answer\s*(.+?)(?=^##\s+|\Z)",
            final_report or "",
        )
        if not match:
            return 0
        body = match.group(1)
        bucket = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+)$", body)
        if not bucket:
            return 0
        line = bucket.group(1)
        return len(re.findall(r"\[C\d+\]", line))

    tier_counts = quality_stats(citations)
    claim_ids = set(re.findall(r"\[C\d+\]", final_report or ""))
    words = len(re.findall(r"\b[\w'-]+\b", final_report or ""))
    section_count = len(re.findall(r"(?m)^##\s+", final_report or ""))
    lower_report = (final_report or "").lower()
    placeholder_hits = detect_placeholder_content(final_report or "")
    boilerplate_markers = (
        "privacy policy",
        "terms of use",
        "all rights reserved",
        "cookie policy",
        "sign in",
        "log in",
        "share on",
    )
    boilerplate_hits = sum(lower_report.count(marker) for marker in boilerplate_markers)
    boilerplate_ratio = boilerplate_hits / max(1, words)
    executive_match = re.search(
        r"(?ims)^##\s+Executive Summary\s*(.+?)(?=^##\s+|\Z)",
        final_report or "",
    )
    executive_text = executive_match.group(1).strip() if executive_match else ""
    directness_markers = ("in short", "the answer", "overall", "this means", "in practice")
    answer_directness = 0.0
    if executive_text:
        marker_bonus = 0.3 if any(token in executive_text.lower() for token in directness_markers) else 0.0
        length_bonus = min(0.5, len(re.findall(r"\b[\w'-]+\b", executive_text)) / 400)
        citation_penalty = min(0.25, len(re.findall(r"\[C\d+\]", executive_text)) / 60)
        answer_directness = max(0.0, min(1.0, 0.25 + marker_bonus + length_bonus - citation_penalty))
    readability_score = max(
        0.0,
        min(
            1.0,
            0.38
            + min(words, 3000) / 6000
            + min(section_count, 16) / 60
            - (len(eval_result.reasons or []) * 0.03)
            - min(0.18, boilerplate_ratio * 8),
        ),
    )
    quality_flags = list(eval_result.reasons or [])
    def _quality_bucket(reason: str) -> str | None:
        lower = reason.lower()
        if "placeholder" in lower or "example.com" in lower:
            return "placeholder_content"
        if "direct answer" in lower or "domain language" in lower or "answer-light" in lower:
            return "top_section_directness"
        if "analytical statements" in lower:
            return "insight_density_low"
        if "provider" in lower or "external providers" in lower:
            return "primary_source_floor"
        if "boilerplate" in lower or "repeated phrase" in lower or "inventory heavy" in lower:
            return "mechanics_overuse_top_sections"
        if "too few claim-grounded references" in lower:
            return "verified_floor_top_sections"
        if "too heavily on constrained/withheld findings" in lower:
            return "ctier_overuse_top_sections"
        if "verification" in lower:
            return "verification_floor"
        return None
    quality_failure_buckets = list(
        dict.fromkeys(
            bucket
            for bucket in (_quality_bucket(reason) for reason in quality_flags)
            if bucket
        )
    )
    narrative_quality_flags: list[str] = []
    for flag in quality_flags:
        lower = flag.lower()
        if "answer-light" in lower or "alignment" in lower or "narrative" in lower:
            narrative_quality_flags.append(flag)
    total_sources = max(1, len(citations))
    tier_a = int(tier_counts.get("A", 0))
    tier_b = int(tier_counts.get("B", 0))
    tier_c = int(tier_counts.get("C", 0))
    unique_providers = len({(c.provider or "").strip().lower() for c in citations if (c.provider or "").strip()})
    if tier_a + tier_b >= max(2, int(0.5 * total_sources)):
        confidence_band = "high"
    elif tier_a + tier_b >= max(1, int(0.2 * total_sources)):
        confidence_band = "mixed"
    else:
        confidence_band = "low"
    source_mix_grade = "A"
    if tier_a + tier_b < 2 or unique_providers < 2:
        source_mix_grade = "B"
    if tier_a + tier_b == 0 or unique_providers <= 1:
        source_mix_grade = "C"
    state_metrics = state_metrics or {}
    claim_mix_metric = state_metrics.get("claim_mix")
    if isinstance(claim_mix_metric, dict):
        asserted_claims = int(claim_mix_metric.get("asserted", 0))
        constrained_claims = int(claim_mix_metric.get("constrained", 0))
        withheld_claims = int(claim_mix_metric.get("withheld", 0))
    else:
        asserted_claims = len(re.findall(r"###\s+Established Evidence", final_report or ""))
        constrained_claims = len(re.findall(r"###\s+Directional / Constrained Findings", final_report or ""))
        withheld_claims = len(re.findall(r"withheld", (final_report or "").lower()))

    source_mix_metric = state_metrics.get("source_mix")
    if isinstance(source_mix_metric, dict):
        source_mix = {
            "tier_ab_count": int(source_mix_metric.get("tier_ab_count", int(tier_counts.get("tier_ab", 0)))),
            "tier_c_count": int(source_mix_metric.get("tier_c_count", int(tier_counts.get("C", 0)))),
            "domain_count": int(source_mix_metric.get("domain_count", 0)),
            "provider_count": int(source_mix_metric.get("provider_count", unique_providers)),
        }
    else:
        source_mix = {
            "tier_ab_count": int(tier_counts.get("tier_ab", 0)),
            "tier_c_count": int(tier_counts.get("C", 0)),
            "domain_count": len({normalized_domain(c.source_url) for c in citations if normalized_domain(c.source_url)}),
            "provider_count": unique_providers,
        }

    confidence_verdict = "high"
    if (
        source_mix["tier_ab_count"] < config.min_ab_sources
        or source_mix["domain_count"] < config.min_unique_domains
        or source_mix["provider_count"] < config.min_unique_providers
    ):
        confidence_verdict = "constrained"
    elif constrained_claims > max(0, asserted_claims):
        confidence_verdict = "mixed"
    elif confidence_band == "mixed":
        confidence_verdict = "mixed"

    quality_retry_attempted = bool(state_metrics.get("quality_retry_attempted", False))
    quality_retry_succeeded = bool(state_metrics.get("quality_retry_succeeded", False))
    provider_alerts = list(state_metrics.get("provider_alerts", []))
    eval_meta = dict(eval_result.meta or {})
    provider_floor_met = bool(
        state_metrics.get(
            "provider_floor_met",
            eval_meta.get("source_ok_for_gate", eval_meta.get("source_ok", False)),
        )
    )
    judge_fallback_used = bool(
        state_metrics.get("judge_fallback_used", eval_meta.get("judge_fallback_used", False))
    )
    constrained_reason_codes = list(
        state_metrics.get("constrained_reason_codes", eval_meta.get("reason_codes", []))
    )
    retrieval_stats_metric = state_metrics.get("retrieval_stats")
    if isinstance(retrieval_stats_metric, dict):
        retrieval_stats = {
            "candidate_count": int(retrieval_stats_metric.get("candidate_count", 0)),
            "filtered_count": int(retrieval_stats_metric.get("filtered_count", 0)),
            "kept_count": int(retrieval_stats_metric.get("kept_count", len(citations))),
            "stale_count": int(retrieval_stats_metric.get("stale_count", 0)),
        }
    else:
        retrieval_stats = {
            "candidate_count": len(citations),
            "filtered_count": 0,
            "kept_count": len(citations),
            "stale_count": 0,
        }
    verification_stats_metric = state_metrics.get("verification_stats")
    if isinstance(verification_stats_metric, dict):
        verification_stats = {
            "verified_count": int(verification_stats_metric.get("verified_count", 0)),
            "constrained_count": int(verification_stats_metric.get("constrained_count", 0)),
            "withheld_count": int(verification_stats_metric.get("withheld_count", 0)),
            "unmet_rules": int(verification_stats_metric.get("unmet_rules", 0)),
        }
    else:
        verification_stats = {
            "verified_count": asserted_claims,
            "constrained_count": constrained_claims,
            "withheld_count": withheld_claims,
            "unmet_rules": 0,
        }
    availability_stats_metric = state_metrics.get("availability_stats")
    if isinstance(availability_stats_metric, dict):
        availability_stats = {
            "open_confirmed_count": int(availability_stats_metric.get("open_confirmed_count", 0)),
            "unknown_count": int(availability_stats_metric.get("unknown_count", 0)),
        }
    else:
        availability_stats = {"open_confirmed_count": 0, "unknown_count": 0}
    quality_verdict = str(state_metrics.get("quality_verdict", confidence_verdict))
    reason_codes = list(dict.fromkeys(constrained_reason_codes))
    subtopic_count = int(state_metrics.get("subtopic_count", 0))
    subtopic_success_count = int(state_metrics.get("subtopic_success_count", 0))
    subtopic_failed_count = int(
        state_metrics.get("subtopic_failed_count", max(0, subtopic_count - subtopic_success_count))
    )
    subtopic_reason_codes = list(state_metrics.get("subtopic_reason_codes", []))
    merge_conflicts_detected = int(state_metrics.get("merge_conflicts_detected", 0))
    editor_input_word_count = int(state_metrics.get("editor_input_word_count", 0))
    if subtopic_count > 0 and subtopic_success_count == 0:
        confidence_verdict = "constrained"
    elif subtopic_failed_count > 0 and confidence_verdict == "high":
        confidence_verdict = "mixed"
    verified_top_section_claims = _count_section_claims("Executive Summary") + _count_direct_answer_bucket("Verified")
    constrained_top_section_claims = _count_direct_answer_bucket("Constrained")
    unknown_top_section_items = _count_direct_answer_bucket("Unknowns")
    stage_idle_timeouts = {
        "planning": config.stream_stage_idle_seconds_planning,
        "research": config.stream_stage_idle_seconds_research,
        "synthesis": config.stream_stage_idle_seconds_synthesis,
        "evaluation": config.stream_stage_idle_seconds_evaluation,
        "finalizing": config.stream_stage_idle_seconds_finalizing,
    }
    timeout_profile_used = {
        "warn_before_idle_ratio": config.stream_warn_before_idle_ratio,
        "max_runtime_seconds": config.stream_max_runtime_seconds,
        "llm_request_timeout_seconds_research": config.llm_request_timeout_seconds_research,
        "llm_request_timeout_seconds_synthesis": config.llm_request_timeout_seconds_synthesis,
        "llm_request_timeout_seconds_correction": config.llm_request_timeout_seconds_correction,
    }
    provider_recovery_actions = list(state_metrics.get("provider_recovery_actions", []))
    quality_verdict_details = {
        "verdict": quality_verdict,
        "reason_codes": reason_codes,
        "quality_failure_buckets": quality_failure_buckets,
        "provider_floor_met": provider_floor_met,
    }
    total_sources = max(1, source_mix["tier_ab_count"] + source_mix["tier_c_count"])
    top_section_metrics = {
        "verified_claims": verified_top_section_claims,
        "ctier_ratio": round(source_mix["tier_c_count"] / total_sources, 3),
        "insight_density": int(state_metrics.get("analytical_statements", 0)),
        "mechanics_ratio": float(state_metrics.get("source_mechanics_ratio", 0.0)),
    }
    query_lower = (query or "").lower()
    opportunity_terms = (
        "scholarship",
        "fellowship",
        "admission",
        "apply",
        "application",
        "deadline",
        "intake",
        "currently available",
        "open now",
        "funded",
    )
    opportunity_query_detected = any(term in query_lower for term in opportunity_terms)
    fallback_mode_used = "none"
    if "insufficient external evidence is available" in (final_report or "").lower():
        fallback_mode_used = "fail_closed"
    elif quality_verdict == "constrained":
        fallback_mode_used = "constrained_registry"

    return {
        "word_count": words,
        "claim_count": len(claim_ids),
        "source_count": len(citations),
        "tier_ab_count": int(tier_counts.get("tier_ab", 0)),
        "quality_flags": quality_flags,
        "quality_failure_buckets": quality_failure_buckets,
        "readability_score": round(readability_score, 3),
        "answer_directness": round(answer_directness, 3),
        "boilerplate_ratio": round(boilerplate_ratio, 4),
        "source_mix_grade": source_mix_grade,
        "narrative_quality_flags": narrative_quality_flags,
        "research_mode_used": config.research_mode,
        "report_structure_mode_used": config.report_structure_mode,
        "availability_scope_applied": config.availability_enforcement_scope,
        "opportunity_query_detected": opportunity_query_detected,
        "report_surface_mode_used": config.report_surface_mode,
        "placeholder_content_detected": bool(placeholder_hits),
        "primary_evidence_ratio": round(
            source_mix["tier_ab_count"] / max(1, source_mix["tier_ab_count"] + source_mix["tier_c_count"]),
            3,
        ),
        "verified_findings_count": int(verification_stats.get("verified_count", 0)),
        "constrained_findings_count": int(verification_stats.get("constrained_count", 0)),
        "quality_retry_attempted": quality_retry_attempted,
        "quality_retry_succeeded": quality_retry_succeeded,
        "provider_floor_met": provider_floor_met,
        "judge_fallback_used": judge_fallback_used,
        "constrained_reason_codes": constrained_reason_codes,
        "provider_alerts": provider_alerts,
        "retrieval_stats": retrieval_stats,
        "verification_stats": verification_stats,
        "availability_stats": availability_stats,
        "reason_codes": reason_codes,
        "quality_verdict": quality_verdict,
        "quality_verdict_details": quality_verdict_details,
        "top_section_metrics": top_section_metrics,
        "fallback_mode_used": fallback_mode_used,
        "quality_block_reasons": reason_codes,
        "subtopic_count": subtopic_count,
        "subtopic_success_count": subtopic_success_count,
        "subtopic_failed_count": subtopic_failed_count,
        "subtopic_reason_codes": subtopic_reason_codes,
        "merge_conflicts_detected": merge_conflicts_detected,
        "editor_input_word_count": editor_input_word_count,
        "source_mix": source_mix,
        "claim_mix": {
            "asserted": asserted_claims,
            "constrained": constrained_claims,
            "withheld": withheld_claims,
        },
        "confidence_verdict": confidence_verdict,
        "source_quality_summary": {
            "tier_a": int(tier_counts.get("A", 0)),
            "tier_b": int(tier_counts.get("B", 0)),
            "tier_c": int(tier_counts.get("C", 0)),
            "tier_ab": int(tier_counts.get("tier_ab", 0)),
            "strict_high_confidence": strict_high_confidence,
            "fail_closed_reason": quality_flags[0] if quality_flags else "",
        },
        "confidence_band": confidence_band,
        "source_tier_ratio": {
            "A": round(tier_a / total_sources, 3),
            "B": round(tier_b / total_sources, 3),
            "C": round(tier_c / total_sources, 3),
        },
        "claim_quality_summary": {
            "asserted_claims": asserted_claims,
            "constrained_claims": constrained_claims,
            "withheld_claims": withheld_claims,
            "contradicted_claims": len(re.findall(r"contradiction", (final_report or "").lower())),
        },
        "uncertainty_summary": {
            "high_confidence_findings": tier_a + tier_b,
            "mixed_confidence_findings": tier_c,
            "unknowns": len(re.findall(r"unknown|uncertain|insufficient", (final_report or "").lower())),
        },
        "query_normalization": state_metrics.get("query_normalization", {}),
        "method_trace_summary": state_metrics.get("method_trace_summary", {}),
        "timeout_profile_used": timeout_profile_used,
        "stage_idle_timeouts": stage_idle_timeouts,
        "provider_recovery_actions": provider_recovery_actions,
        "verified_top_section_claims": verified_top_section_claims,
        "constrained_top_section_claims": constrained_top_section_claims,
        "unknown_top_section_items": unknown_top_section_items,
        "startup_profile": startup_profile or {},
    }


def run_research(query: str, *, config: RunConfig | None = None) -> ResearchResult:
    cfg = config or load_config()
    hitl_input_provider = _default_hitl_input if cfg.interactive_hitl else None
    started = perf_counter()
    startup_profile: dict[str, object] = {
        "runtime_profile": cfg.runtime_profile,
        "startup_guard_mode": cfg.startup_guard_mode,
        "optional_dependency_status": optional_dependency_status(),
        "startup_reason_codes": startup_reason_codes(startup_guard_mode=cfg.startup_guard_mode),
        "features": {
            "distributed": cfg.enable_distributed,
            "observability": cfg.enable_observability,
            "storage": cfg.enable_storage,
        },
    }
    with GraphRuntime.from_config(cfg) as runtime:
        probe = runtime.mcp_client.startup_probe()
        startup_profile["mcp"] = {
            "transport_enabled": probe.transport_enabled,
            "transport_active": probe.transport_active,
            "fallback_active": probe.fallback_active,
            "fallback_reason": probe.fallback_reason,
            "web_healthy": probe.web_healthy,
            "local_healthy": probe.local_healthy,
        }
        startup_profile["dependencies"] = dependency_health(cfg)["subsystems"]
        final_state = run_graph(query, runtime, hitl_input_provider=hitl_input_provider)

    citations = _as_citations(final_state.get("citations", []))
    eval_state = final_state.get("eval_result") or EvalResult()
    eval_result = (
        eval_state
        if isinstance(eval_state, EvalResult)
        else EvalResult.model_validate(eval_state)
    )
    status = final_state.get("status", "completed")
    record_graph_run(status=status, duration_seconds=perf_counter() - started)
    cleanup_old_artifacts(
        [cfg.output_dir, cfg.logs_dir],
        cfg.retention_days,
    )
    result = ResearchResult(
        run_id=final_state["run_id"],
        query=query,
        final_report=final_state.get("final_report", final_state.get("report_draft", "")),
        citations=citations,
        eval_result=eval_result,
        low_confidence=bool(final_state.get("low_confidence", False)),
        status=status,
        artifacts_path=final_state.get("artifacts_path", ""),
        tenant_id=cfg.tenant_id,
        report_meta=_report_meta(
            final_state.get("final_report", final_state.get("report_draft", "")),
            citations,
            eval_result,
            query=query,
            config=cfg,
            state_metrics=final_state.get("metrics", {}),
            strict_high_confidence=cfg.strict_high_confidence,
            startup_profile=startup_profile,
        ),
    )
    upsert_registry_record(cfg, result)
    return result


def resume_research(run_id: str, *, config: RunConfig | None = None) -> ResearchResult:
    cfg = config or load_config()
    return load_result_from_artifacts(cfg, run_id)


if __name__ == "__main__":
    # Useful for quick manual execution.
    result = run_research("Cloud Hive dry run query", config=load_config({"interactive_hitl": False}))
    print(result.model_dump_json(indent=2))
