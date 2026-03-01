from __future__ import annotations

import re
from typing import Any

from agents.model_router import ModelRouter
from core.citations import (
    normalize_url,
    validate_claim_level_citations,
    validate_source_integrity,
)
from core.models import Citation, EvalResult, RunConfig
from core.query_profile import profile_query
from core.report_quality import assess_report_quality
from core.verification import query_requires_open_availability
from evals.judges.groq_judge import judge_with_groq
from evals.judges.hf_judge import judge_with_hf
from evals.judges.llm_judge import judge_with_llm
from evals.judges.stub_judge import judge_with_stub


class DeepEvalNode:
    def __init__(self, config: RunConfig, runtime: Any = None):
        self.config = config
        self.runtime = runtime

    def evaluate(
        self,
        query: str,
        report: str,
        citations: list[Citation],
        *,
        branch_coverage: dict[str, Any] | None = None,
    ) -> EvalResult:
        min_words = (
            self.config.target_report_words_peak_min
            if self.config.research_mode == "peak"
            else self.config.min_report_words_deep
            if self.config.research_depth == "deep"
            else None
        )
        min_claims = (
            max(self.config.min_claims_deep, self.config.min_primary_claims)
            if self.config.research_mode == "peak"
            else self.config.min_claims_deep
            if self.config.research_depth == "deep"
            else None
        )
        min_ab_sources = (
            max(self.config.min_tier_ab_sources, self.config.min_ab_sources)
            if self.config.primary_source_policy == "strict"
            else self.config.min_tier_ab_sources
        )
        min_unique_domains = (
            self.config.min_unique_domains
            if self.config.primary_source_policy == "strict"
            else 0
        )
        max_ctier_ratio = (
            self.config.max_ctier_claim_ratio
            if self.config.primary_source_policy == "strict"
            else 1.0
        )
        citation_ok, citation_reasons, coverage = validate_claim_level_citations(
            report, citations, min_coverage=self.config.citation_threshold
        )
        unique_external_urls = len(
            {normalize_url(c.source_url) for c in citations if normalize_url(c.source_url)}
        )
        enforce_strict_confidence = (
            self.config.strict_high_confidence
            and self.config.source_quality_bar == "high_confidence"
        )
        min_external_sources = (
            self.config.min_external_sources
            if unique_external_urls >= self.config.min_external_sources
            else 2
            if (self.config.quota_pressure_mode and unique_external_urls >= 2 and not enforce_strict_confidence)
            else self.config.min_external_sources
        )
        source_ok, source_reasons, source_stats = validate_source_integrity(
            citations,
            source_policy=self.config.source_policy,
            min_external_sources=min_external_sources,
            min_unique_domains=min_unique_domains,
            min_unique_providers=self.config.min_unique_providers,
            allow_relaxed_diversity=self.config.quota_pressure_mode and not enforce_strict_confidence,
            min_tier_ab_sources=min_ab_sources,
            max_ctier_claim_ratio=max_ctier_ratio,
            require_corroboration_for_tier_c=self.config.require_corroboration_for_tier_c,
        )
        constrained_output_detected = (
            "### Directional / Constrained Findings" in report
            and "### Withheld Claims" in report
        ) or ("constrained-actionable mode" in report.lower())
        source_ok_for_gate = source_ok
        if (
            not source_ok
            and self.config.truth_mode == "balanced"
            and self.config.insufficient_evidence_output == "constrained_actionable"
            and constrained_output_detected
        ):
            source_ok_for_gate = True
            source_reasons = list(source_reasons) + [
                "Source floor not fully met; constrained actionable mode accepted with explicit uncertainty."
            ]
        quality_ok, quality_reasons, _ = assess_report_quality(
            report,
            query=query,
            depth=self.config.research_depth,
            min_words=min_words,
            min_claims=min_claims,
            report_structure_mode=self.config.report_structure_mode,
            insight_density_min=self.config.insight_density_min,
            mechanics_ratio_max_top_sections=self.config.mechanics_ratio_max_top_sections,
            top_section_min_verified_claims=self.config.top_section_min_verified_claims,
            top_section_max_ctier_ratio=self.config.top_section_max_ctier_ratio,
        )
        verified_rows = len(
            re.findall(r"\|\s*\[C\d+\]\s*\|\s*verified\s*\|", report or "", flags=re.IGNORECASE)
        )
        constrained_rows = len(
            re.findall(r"\|\s*\[C\d+\]\s*\|\s*constrained\s*\|", report or "", flags=re.IGNORECASE)
        )
        withheld_rows = len(
            re.findall(r"\|\s*\[C\d+\]\s*\|\s*withheld\s*\|", report or "", flags=re.IGNORECASE)
        )
        verification_ok = True
        verification_reasons: list[str] = []
        if self.config.report_artifact_mode != "narrative_only":
            if "## verified findings register" not in (report or "").lower():
                verification_ok = False
                verification_reasons.append("Missing Verified Findings Register section.")
        if self.config.fact_mode == "strict":
            if verified_rows < max(1, self.config.verified_findings_min):
                verification_ok = False
                verification_reasons.append(
                    f"Verified findings count is {verified_rows}; minimum required is {self.config.verified_findings_min}."
                )
        query_profile = profile_query(
            query,
            dual_use_depth=self.config.dual_use_depth,
            cleanup_mode=self.config.query_cleanup_mode,
        )
        needs_open = query_requires_open_availability(
            query_profile,
            availability_policy=self.config.availability_policy,
            availability_enforcement_scope=self.config.availability_enforcement_scope,
            opportunity_query_detection=self.config.opportunity_query_detection,
            query=query,
        )
        if needs_open and "open_status_unknown" in (report or "").lower():
            verification_ok = False
            verification_reasons.append(
                "Currently-available query still contains unknown open-status claims."
            )

        # Determine judge
        if self.config.judge_provider == "stub":
            result = judge_with_stub(query, report, citations, coverage)
        elif self.config.judge_provider == "hf":
            result = judge_with_hf(query, report, citations, coverage, self.config)
        elif self.runtime and self.runtime.model_router:
            # Use router
            router: ModelRouter = self.runtime.model_router
            model_selection = router.select_model(
                task_type="evaluation",
                context_size=len(report),
                latency_budget_ms=2000,
                tenant_tier="default",  # Could come from state if passed
            )
            try:
                client = self.runtime.get_llm_client(model_selection.provider)
                result = judge_with_llm(
                    query, report, citations, coverage, self.config, client,
                    model_selection.provider, model_selection.model_name
                )
            except Exception:
                # Fallback
                result = judge_with_groq(query, report, citations, coverage, self.config)
        else:
            # Default groq pathway (with heuristic fallback when key is missing).
            result = judge_with_groq(query, report, citations, coverage, self.config)

        reasons: list[str] = []
        reasons.extend(result.reasons or [])
        if not citation_ok:
            reasons.extend(citation_reasons)
        if not source_ok:
            reasons.extend(source_reasons)
        if not quality_ok:
            reasons.extend(quality_reasons)
        if not verification_ok:
            reasons.extend(verification_reasons)
        if result.faithfulness < self.config.faithfulness_threshold:
            reasons.append(
                "Faithfulness score below threshold: "
                f"{result.faithfulness:.2f} < {self.config.faithfulness_threshold:.2f}"
            )
        if result.relevancy < self.config.relevancy_threshold:
            reasons.append(
                "Relevancy score below threshold: "
                f"{result.relevancy:.2f} < {self.config.relevancy_threshold:.2f}"
            )
        if coverage < self.config.citation_threshold:
            reasons.append(
                "Citation coverage below threshold: "
                f"{coverage:.2f} < {self.config.citation_threshold:.2f}"
            )
        deduped_reasons = list(dict.fromkeys(r for r in reasons if r.strip()))
        pass_gate = (
            result.faithfulness >= self.config.faithfulness_threshold
            and result.relevancy >= self.config.relevancy_threshold
            and coverage >= self.config.citation_threshold
            and quality_ok
            and verification_ok
            and source_ok_for_gate
        )
        if not pass_gate and not deduped_reasons:
            deduped_reasons.append("Evaluation gate failed due to unmet quality constraints.")
        reason_codes: list[str] = []
        if not citation_ok:
            reason_codes.append("citation_coverage")
        if not source_ok:
            reason_codes.append("provider_diversity")
            if int(source_stats.get("tier_ab_sources", 0)) < max(1, min_ab_sources):
                reason_codes.append("primary_source_floor")
        if not quality_ok:
            for issue in quality_reasons:
                lower = issue.lower()
                if "placeholder" in lower or "example.com" in lower:
                    reason_codes.append("placeholder_content")
                if "narrative" in lower or "domain language" in lower:
                    reason_codes.append("narrative_directness")
                if "analytical statements" in lower:
                    reason_codes.append("insight_density_low")
                if "boilerplate" in lower or "repeated phrase" in lower:
                    reason_codes.append("source_signal_quality")
                if "inventory heavy" in lower or "answer-light" in lower:
                    reason_codes.append("mechanics_overuse_top_sections")
                if "too few claim-grounded references" in lower:
                    reason_codes.append("verified_floor_top_sections")
                if "too heavily on constrained/withheld findings" in lower:
                    reason_codes.append("ctier_overuse_top_sections")
        if result.faithfulness < self.config.faithfulness_threshold:
            reason_codes.append("faithfulness")
        if result.relevancy < self.config.relevancy_threshold:
            reason_codes.append("relevancy")
        if coverage < self.config.citation_threshold:
            reason_codes.append("citation_threshold")
        if not verification_ok:
            reason_codes.append("verification_floor")
        if branch_coverage and int(branch_coverage.get("subtopic_failed_count", 0)) > 0:
            reason_codes.append("subtopic_partial_failure")
        reason_codes = list(dict.fromkeys(reason_codes))
        coverage_meta = dict(branch_coverage or {})
        if coverage_meta and int(coverage_meta.get("subtopic_failed_count", 0)) > 0:
            deduped_reasons = list(
                dict.fromkeys(
                    [
                        *deduped_reasons,
                        (
                            "Subtopic coverage degraded: "
                            f"{coverage_meta.get('subtopic_success_count', 0)}/"
                            f"{coverage_meta.get('subtopic_count', 0)} branches completed."
                        ),
                    ]
                )
            )
        return EvalResult(
            faithfulness=result.faithfulness,
            relevancy=result.relevancy,
            citation_coverage=coverage,
            pass_gate=pass_gate,
            reasons=deduped_reasons,
            meta={
                **dict(result.meta or {}),
                "source_ok": source_ok,
                "source_ok_for_gate": source_ok_for_gate,
                "source_reasons": source_reasons,
                "source_stats": source_stats,
                "citation_ok": citation_ok,
                "quality_ok": quality_ok,
                "quality_reasons": quality_reasons,
                "verification_ok": verification_ok,
                "verification_reasons": verification_reasons,
                "verification_counts": {
                    "verified_count": verified_rows,
                    "constrained_count": constrained_rows,
                    "withheld_count": withheld_rows,
                },
                "branch_coverage": coverage_meta,
                "reason_codes": reason_codes,
            },
        )
