from __future__ import annotations

import logging

from agents.prompts import CRITIC_PROMPT
from core.citations import (
    dedupe_citations,
    extract_claim_ids,
    normalize_url,
    validate_claim_level_citations,
    validate_source_integrity,
)
from core.models import Citation
from core.report_formatter import format_report_with_sources
from core.report_quality import assess_report_quality
from graph.runtime import GraphRuntime
from graph.state import ResearchState

logger = logging.getLogger(__name__)


def _adaptive_min_external_sources(
    available_sources: int,
    configured_min: int,
    *,
    allow_relax: bool,
) -> int:
    if available_sources >= configured_min:
        return configured_min
    if allow_relax and available_sources >= 2:
        return 2
    return configured_min


def _effective_min_words(runtime: GraphRuntime) -> int | None:
    if runtime.config.research_mode == "peak":
        return runtime.config.target_report_words_peak_min
    if runtime.config.research_depth == "deep":
        return runtime.config.min_report_words_deep
    return None


def _effective_min_claims(runtime: GraphRuntime) -> int | None:
    if runtime.config.research_mode == "peak":
        return max(runtime.config.min_claims_deep, runtime.config.min_primary_claims)
    if runtime.config.research_depth == "deep":
        return runtime.config.min_claims_deep
    return None


def _effective_min_ab_sources(runtime: GraphRuntime) -> int:
    if runtime.config.primary_source_policy == "strict":
        return max(runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources)
    return runtime.config.min_tier_ab_sources


def _effective_min_unique_domains(runtime: GraphRuntime) -> int:
    if runtime.config.primary_source_policy == "strict":
        return runtime.config.min_unique_domains
    return 0


def _effective_max_ctier_ratio(runtime: GraphRuntime) -> float:
    if runtime.config.primary_source_policy == "strict":
        return runtime.config.max_ctier_claim_ratio
    return 1.0


def _model_kwargs(provider: str, model_name: str, system_msg: str, user_msg: str) -> dict:
    if provider in {"openai", "groq", "openrouter"}:
        return {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        }
    if provider == "anthropic":
        return {
            "model": model_name,
            "max_tokens": 3200,
            "system": system_msg,
            "messages": [{"role": "user", "content": user_msg}],
        }
    return {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
    }


def create_self_correction_node(runtime: GraphRuntime):
    def _is_timeout_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text

    def self_correction_node(state: ResearchState) -> dict:
        correction_timeout = False
        report = state.get("report_draft", "")
        citations = dedupe_citations(state.get("citations", []))
        source_index = dict(state.get("source_index", {}))
        context_docs = state.get("context_docs", [])
        tenant_context = state.get("tenant_context")
        tenant_tier = tenant_context.quota_tier if tenant_context else "default"

        min_words = _effective_min_words(runtime)
        min_claims = _effective_min_claims(runtime)
        min_ab_sources = _effective_min_ab_sources(runtime)
        min_unique_domains = _effective_min_unique_domains(runtime)
        max_ctier_ratio = _effective_max_ctier_ratio(runtime)

        citation_ok, citation_reasons, coverage = validate_claim_level_citations(
            report, citations, min_coverage=runtime.config.citation_threshold
        )
        source_ok, source_reasons, source_stats = validate_source_integrity(
            citations,
            source_policy=runtime.config.source_policy,
            min_external_sources=_adaptive_min_external_sources(
                source_stats_count := len(
                    {normalize_url(c.source_url) for c in citations if normalize_url(c.source_url)}
                ),
                runtime.config.min_external_sources,
                allow_relax=runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence,
            ),
            min_unique_domains=min_unique_domains,
            min_unique_providers=runtime.config.min_unique_providers,
            allow_relaxed_diversity=runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence,
            min_tier_ab_sources=min_ab_sources,
            max_ctier_claim_ratio=max_ctier_ratio,
            require_corroboration_for_tier_c=runtime.config.require_corroboration_for_tier_c,
        )
        quality_ok, quality_reasons, quality_metrics = assess_report_quality(
            report,
            query=state["query"],
            depth=runtime.config.research_depth,
            min_words=min_words,
            min_claims=min_claims,
            report_structure_mode=runtime.config.report_structure_mode,
            insight_density_min=runtime.config.insight_density_min,
            mechanics_ratio_max_top_sections=runtime.config.mechanics_ratio_max_top_sections,
            top_section_min_verified_claims=runtime.config.top_section_min_verified_claims,
            top_section_max_ctier_ratio=runtime.config.top_section_max_ctier_ratio,
        )

        if citation_ok and source_ok and quality_ok:
            normalized_report, normalized_citations = format_report_with_sources(
                report,
                citations,
                source_policy=runtime.config.source_policy,
                report_presentation=runtime.config.report_presentation,
                sources_presentation=runtime.config.sources_presentation,
                show_technical_sections_default=runtime.config.show_technical_sections_default,
                report_surface_mode=runtime.config.report_surface_mode,
                report_structure_mode=runtime.config.report_structure_mode,
                max_sources_snapshot=runtime.config.max_sources_snapshot,
            )
            return {
                "report_draft": normalized_report,
                "citations": normalized_citations,
                "status": "corrected",
                "logs": ["Self-correction check passed (quality + source integrity)."],
            }

        reasons = [*citation_reasons, *source_reasons, *quality_reasons]
        if not context_docs:
            note = (
                "\n\n## Quality Notes\n"
                "- Self-correction skipped: no context docs available for rewrite.\n"
                f"- Outstanding issues: {', '.join(reasons[:4]) if reasons else 'Unknown'}."
            )
            normalized_report, normalized_citations = format_report_with_sources(
                report + note,
                citations,
                source_policy=runtime.config.source_policy,
                report_presentation=runtime.config.report_presentation,
                sources_presentation=runtime.config.sources_presentation,
                show_technical_sections_default=runtime.config.show_technical_sections_default,
                report_surface_mode=runtime.config.report_surface_mode,
                report_structure_mode=runtime.config.report_structure_mode,
                max_sources_snapshot=runtime.config.max_sources_snapshot,
            )
            return {
                "report_draft": normalized_report,
                "citations": normalized_citations,
                "status": "corrected",
                "logs": ["Self-correction skipped due to missing context."],
            }

        model_selection = runtime.model_router.select_model(
            task_type="correction",
            context_size=len(report),
            latency_budget_ms=15000,
            tenant_tier=tenant_tier,
            tenant_context=tenant_context,
            plan_complexity="medium",
        )

        try:
            client = runtime.get_llm_client(
                model_selection.provider,
                request_timeout_seconds=runtime.config.llm_request_timeout_seconds_correction,
            )
            user_msg = (
                f"Original Report:\n{report}\n\n"
                f"Validation Issues:\n{chr(10).join(reasons)}\n\n"
                "Rewrite to satisfy all requirements. Keep valid claim IDs and do not invent sources.\n"
                "Prioritize narrative-first structure: Executive Summary, Direct Answer, Key Findings, Recommendations, 12-Month Action Plan.\n"
                "Keep technical sections informative but appendix-oriented, and keep Sources Used as the final section.\n"
                "Reduce repetitive sentence scaffolding and avoid source-inventory tone in the top sections."
            )
            kwargs = _model_kwargs(
                model_selection.provider,
                model_selection.model_name,
                CRITIC_PROMPT,
                user_msg,
            )
            content = ""
            if model_selection.provider in {"openai", "groq", "openrouter"}:
                resp = client.chat.completions.create(
                    **kwargs,
                    max_tokens=3600 if runtime.config.research_depth == "deep" else 2200,
                    temperature=model_selection.temperature or 0.2,
                )
                content = resp.choices[0].message.content or ""
            elif model_selection.provider == "anthropic":
                resp = client.messages.create(
                    **kwargs,
                    temperature=model_selection.temperature or 0.2,
                )
                content = resp.content[0].text if resp.content else ""
            elif model_selection.provider == "huggingface":
                resp = client.chat_completion(
                    **kwargs,
                    max_tokens=2200,
                    temperature=model_selection.temperature or 0.2,
                )
                content = resp.choices[0].message.content or ""

            revised_report = content.strip() or report
            existing_claims = {c.claim_id for c in citations}
            for claim_id in extract_claim_ids(revised_report):
                if claim_id in existing_claims:
                    continue
                doc = source_index.get(claim_id)
                if not doc:
                    continue
                citations.append(
                    Citation(
                        claim_id=claim_id,
                        source_url=normalize_url(doc.url),
                        title=doc.title,
                        provider=doc.provider,
                        evidence=(doc.snippet or "")[:220],
                        source_tier=str((doc.meta or {}).get("source_tier") or "unknown"),  # type: ignore[arg-type]
                        confidence=str((doc.meta or {}).get("confidence") or "unknown"),  # type: ignore[arg-type]
                    )
                )
                existing_claims.add(claim_id)

            revised_report, revised_citations = format_report_with_sources(
                revised_report,
                citations,
                source_policy=runtime.config.source_policy,
                report_presentation=runtime.config.report_presentation,
                sources_presentation=runtime.config.sources_presentation,
                show_technical_sections_default=runtime.config.show_technical_sections_default,
                report_surface_mode=runtime.config.report_surface_mode,
                report_structure_mode=runtime.config.report_structure_mode,
                max_sources_snapshot=runtime.config.max_sources_snapshot,
            )
            revised_citation_ok, revised_citation_reasons, _ = validate_claim_level_citations(
                revised_report,
                revised_citations,
                min_coverage=runtime.config.citation_threshold,
            )
            revised_source_ok, revised_source_reasons, revised_source_stats = (
                validate_source_integrity(
                    revised_citations,
                    source_policy=runtime.config.source_policy,
                    min_external_sources=_adaptive_min_external_sources(
                        revised_source_count := len(
                            {
                                normalize_url(c.source_url)
                                for c in revised_citations
                                if normalize_url(c.source_url)
                            }
                        ),
                        runtime.config.min_external_sources,
                        allow_relax=runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence,
                    ),
                    min_unique_domains=min_unique_domains,
                    min_unique_providers=runtime.config.min_unique_providers,
                    allow_relaxed_diversity=runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence,
                    min_tier_ab_sources=min_ab_sources,
                    max_ctier_claim_ratio=max_ctier_ratio,
                    require_corroboration_for_tier_c=runtime.config.require_corroboration_for_tier_c,
                )
            )
            revised_quality_ok, revised_quality_reasons, _ = assess_report_quality(
                revised_report,
                query=state["query"],
                depth=runtime.config.research_depth,
                min_words=min_words,
                min_claims=min_claims,
                report_structure_mode=runtime.config.report_structure_mode,
                insight_density_min=runtime.config.insight_density_min,
                mechanics_ratio_max_top_sections=runtime.config.mechanics_ratio_max_top_sections,
                top_section_min_verified_claims=runtime.config.top_section_min_verified_claims,
                top_section_max_ctier_ratio=runtime.config.top_section_max_ctier_ratio,
            )

            if revised_citation_ok and revised_source_ok and revised_quality_ok:
                runtime.tracer.event(
                    state["run_id"],
                    "self_correction",
                    "Applied LLM correction",
                    payload={
                        "provider": model_selection.provider,
                        "model": model_selection.model_name,
                        "external_sources": revised_source_count,
                    },
                )
                return {
                    "report_draft": revised_report,
                    "citations": revised_citations,
                    "status": "corrected",
                    "logs": [f"Self-correction rewritten by {model_selection.model_name}."],
                }

            note = (
                "\n\n## Quality Notes\n"
                "- Residual quality checks are still below target.\n"
                f"- Citation issues: {', '.join(revised_citation_reasons[:2]) or 'none'}\n"
                f"- Source issues: {', '.join(revised_source_reasons[:2]) or 'none'}\n"
                f"- Quality issues: {', '.join(revised_quality_reasons[:2]) or 'none'}\n"
                f"- Source stats: {revised_source_stats}\n"
                "- Use this draft with caution."
            )
            runtime.tracer.event(
                state["run_id"],
                "self_correction",
                "Applied fallback correction notes",
                payload={
                    "coverage_before": coverage,
                    "quality_metrics": quality_metrics,
                    "source_count": source_stats_count,
                },
            )
            return {
                "report_draft": revised_report + note,
                "citations": revised_citations,
                "status": "corrected",
                "logs": ["Self-correction appended residual quality notes."],
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("Correction LLM failed: %s", exc)
            if _is_timeout_error(exc):
                correction_timeout = True
                runtime.tracer.event(
                    state["run_id"],
                    "self_correction",
                    "Self-correction timeout",
                    payload={"reason_code": "llm_timeout_correction"},
                )

        note = (
            "\n\n## Quality Notes\n"
            f"- Source integrity stats: {source_stats}\n"
            f"- Structural quality metrics: {quality_metrics}\n"
            f"- Outstanding issues: {', '.join(reasons[:3]) if reasons else 'Unknown'}"
        )
        if correction_timeout:
            note += "\n- Reason code: llm_timeout_correction"
        normalized_report, normalized_citations = format_report_with_sources(
            report + note,
            citations,
            source_policy=runtime.config.source_policy,
            report_presentation=runtime.config.report_presentation,
            sources_presentation=runtime.config.sources_presentation,
            show_technical_sections_default=runtime.config.show_technical_sections_default,
            report_surface_mode=runtime.config.report_surface_mode,
            report_structure_mode=runtime.config.report_structure_mode,
            max_sources_snapshot=runtime.config.max_sources_snapshot,
        )
        return {
            "report_draft": normalized_report,
            "citations": normalized_citations,
            "status": "corrected",
            "logs": ["Self-correction fallback appended quality notes."],
        }

    return self_correction_node
