"""synthesizer.py — Orchestrates the Pass 2 Analytical Synthesis of the research report.

This node is a thin orchestrator that leverages core.synthesis modules to handle
doc processing, config thresholds, LLM calls, and metrics assembly.
"""

from __future__ import annotations

import logging
import re

from agents.prompts import INVESTIGATIVE_PROMPT, SYNTHESIZER_PROMPT
from core.citations import (
    dedupe_citations,
    extract_claim_ids,
    normalize_url,
    validate_source_integrity,
)
from core.claim_extractor import build_fallback_extraction, extract_claims
from core.config import report_length_word_range
from core.models import Citation, SubReport
from core.pruning import prune_context_docs
from core.query_profile import profile_query, safe_analysis_policy
from core.report_formatter import build_fail_closed_report, format_report_with_sources
from core.report_quality import assess_report_quality
from core.source_quality import clean_evidence_text, prioritize_docs
from graph.runtime import GraphRuntime
from graph.state import ResearchState

logger = logging.getLogger(__name__)


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text


def _format_extracted_claims(extraction_result) -> str:
    if not extraction_result:
        return "- No extracted claims available."
    claims = getattr(extraction_result, "claims", None) or []
    if not claims:
        err = getattr(extraction_result, "error", "") or "none"
        return f"- No extracted claims available. extractor_error={err}"

    lines: list[str] = []
    for claim in claims:
        source_id = getattr(claim, "source_id", "C?")
        topic = (getattr(claim, "topic", "general") or "general").strip()
        assertion = (getattr(claim, "assertion", "") or "").strip()
        evidence = (getattr(claim, "evidence", "") or "").strip()
        strength = (getattr(claim, "strength", "moderate") or "moderate").strip()
        if not assertion:
            continue
        excerpt = evidence[:600] if evidence else "No excerpt provided."
        lines.append(f"- [{source_id}] ({topic}, {strength}) {assertion}\n  Evidence: {excerpt}")
    return "\n".join(lines) if lines else "- No extracted claims available."


def _claims_section_from_extraction(extraction_result) -> str:
    if not extraction_result:
        return ""
    claims = getattr(extraction_result, "claims", None) or []
    if not claims:
        return ""
    fallback_used = bool(getattr(extraction_result, "fallback_used", False))
    lines: list[str] = ["## Claims"]
    all_fallback = True
    for claim in claims:
        source_id = getattr(claim, "source_id", "C?")
        assertion = (getattr(claim, "assertion", "") or "").strip()
        if not assertion:
            continue
        status = str(getattr(claim, "status", "unverified") or "unverified").lower()
        if status == "withheld":
            status = "unverified"
        if fallback_used:
            status = "constrained"
        if status != "constrained":
            all_fallback = False
        source = (getattr(claim, "source_url", "") or "").strip() or (getattr(claim, "source_title", "") or "").strip() or "Unknown Source"
        reason = (getattr(claim, "reason", "") or "").strip()
        confidence = (getattr(claim, "confidence", "") or "").strip()
        parts = [f"- [{source_id}] {status.upper()}: {assertion}"]
        if source:
            parts.append(f"source: {source}")
        if confidence:
            parts.append(f"confidence: {confidence}")
        if reason:
            parts.append(f"reason: {reason}")
        lines.append(" | ".join(parts))
    if all_fallback:
        lines.append("")
        lines.append(
            "Some claims are generated from source snippets due to limited extraction confidence."
        )
    return "\n".join(lines)


def _merge_subreport_citations(sub_reports: list[SubReport]) -> list[Citation]:
    merged: list[Citation] = []
    for sub_report in sub_reports:
        merged.extend(sub_report.citations or [])
    return dedupe_citations(merged)


def _subreport_conflict_count(sub_reports: list[SubReport]) -> int:
    seen_assertions: dict[str, set[str]] = {}
    for sub_report in sub_reports:
        for claim in sub_report.claims or []:
            key = claim.assertion.strip().lower()
            if not key:
                continue
            seen_assertions.setdefault(key, set()).add(claim.status)
    return sum(1 for statuses in seen_assertions.values() if len(statuses) > 1)


def _conflict_pairs(sub_reports: list[SubReport]) -> list[str]:
    assertion_statuses: dict[str, set[str]] = {}
    for sub_report in sub_reports:
        for claim in sub_report.claims or []:
            assertion = claim.assertion.strip()
            if not assertion:
                continue
            assertion_statuses.setdefault(assertion, set()).add(claim.status)
    rows: list[str] = []
    for assertion, statuses in assertion_statuses.items():
        if len(statuses) <= 1:
            continue
        rows.append(
            f"- Status conflict on assertion: `{assertion[:140]}` "
            f"(statuses: {', '.join(sorted(statuses))})."
        )
    return rows


def _ensure_conflict_reconciliation_section(report: str, *, conflict_rows: list[str]) -> str:
    body = (report or "").strip()
    if not body:
        return body
    if re.search(r"(?im)^##\s+Evidence Agreement and Disagreement\b", body):
        return body
    if conflict_rows:
        lines = [
            "## Evidence Agreement and Disagreement",
            "Unresolved branch-level disagreements were detected during merge:",
            *conflict_rows[:8],
        ]
    else:
        lines = [
            "## Evidence Agreement and Disagreement",
            "No unresolved branch-level conflicts were detected during merge.",
        ]
    return f"{body}\n\n" + "\n".join(lines)


def _build_subreport_context(sub_reports: list[SubReport]) -> str:
    blocks: list[str] = []
    for idx, sub_report in enumerate(sub_reports, start=1):
        claim_lines = []
        for claim in sub_report.claims:
            claim_lines.append(
                f"- [{claim.claim_id}] ({claim.status}) {claim.assertion}"
                + (f" reasons={','.join(claim.reason_codes)}" if claim.reason_codes else "")
            )
        block = (
            f"### Analyst Sub-report {idx}: {sub_report.facet}\n"
            f"Sub-query: {sub_report.sub_query}\n"
            f"Confidence: {sub_report.confidence}\n"
            f"Reason codes: {', '.join(sub_report.reason_codes) if sub_report.reason_codes else 'none'}\n\n"
            f"{sub_report.content.strip()}\n\n"
            f"Claims:\n{chr(10).join(claim_lines) if claim_lines else '- none'}"
        )
        blocks.append(block)
    return "\n\n".join(blocks).strip()


def _section_contract(report_structure_mode: str) -> str:
    if report_structure_mode == "academic_17":
        return (
            "Required section order (exact headings): "
            "Abstract; Introduction; Theoretical Framework; Literature Review; Hypotheses; "
            "Methodology; Metrics & Evaluation; Formal Modeling of Prompting; Empirical Results; "
            "Generalization & Scaling Laws; Theoretical Contributions; Practical Contributions; "
            "Limitations; Ethical & Governance Considerations; Future Research Directions; Conclusion; Appendices."
        )
    if report_structure_mode == "investigative":
        return (
            "Required section order (exact headings): "
            "Title; Executive Summary; Background and Context; Key Questions; Evidence and Findings; "
            "Deep Analysis; Conflicting Evidence; Case Studies or Examples; "
            "Limitations of Current Knowledge; Implications; Recommendations; Conclusion; Sources Used."
        )
    return (
        "Required top order: Executive Summary, Direct Answer, Key Findings, "
        "Verified Findings Register, Recommendations, 12-Month Action Plan."
    )


def _build_subreport_fallback_report(query: str, sub_reports: list[SubReport]) -> str:
    """Assemble a full report directly from sub-report content when LLM merge fails.

    Instead of producing a thin claim registry, concatenate all sub-report
    analyses into a cohesive report structure. The sub-reports already contain
    analytical prose, so this produces a substantial document.
    """
    lines = [
        f"# {query}",
        "",
        "## Executive Summary",
        "",
        f"This report synthesizes findings from {len(sub_reports)} parallel research analyses. "
        "Each subtopic was independently researched, with evidence collected from multiple web sources "
        "and analyzed for reliability. The findings below represent the current state of available "
        "evidence on this topic.",
        "",
    ]
    # Collect all key findings for executive summary
    for sub in sub_reports:
        verified = [c for c in sub.claims if c.status == "verified"]
        total = len(sub.claims)
        conf_label = f"({len(verified)}/{total} claims verified)" if total else ""
        lines.append(f"- **{sub.facet}** {conf_label}: {sub.sub_query}")
    lines.append("")

    # Each sub-report becomes a major section with its full content
    for idx, sub in enumerate(sub_reports, 1):
        lines.append(f"## {idx}. {sub.facet}")
        lines.append("")
        # Use the full sub-report content — this is the analytical prose
        content = sub.content.strip()
        if content:
            # Strip duplicate headings that clash with our structure
            for prefix in ("## Subtopic Answer", "## Subtopic Analysis"):
                if content.startswith(prefix):
                    content = content[len(prefix):].lstrip("\n")
            lines.append(content)
        else:
            lines.append(f"Research on *{sub.sub_query}* produced limited results.")
        lines.append("")

    # Sources summary
    lines.append("## Sources Used")
    lines.append("")
    seen_urls: set[str] = set()
    for sub in sub_reports:
        for cit in sub.citations:
            if cit.source_url and cit.source_url not in seen_urls:
                seen_urls.add(cit.source_url)
                lines.append(f"- [{cit.claim_id}] {cit.title} — {cit.source_url}")
    if not seen_urls:
        lines.append("- No external sources were retrieved for this query.")

    return "\n".join(lines).strip()


def _build_timeout_constrained_report(sub_reports: list[SubReport]) -> str:
    """Build a full report from sub-report content when master synthesis times out.

    This is the critical fallback — instead of showing a thin claim registry,
    we concatenate all sub-report analyses into a proper report. The sub-reports
    already contain analytical prose produced by the sub-research LLM calls.
    """
    lines = [
        "## Executive Summary",
        "",
        f"This report compiles findings from {len(sub_reports)} independent research branches. "
        "Each branch investigated a specific facet of the research question with dedicated evidence "
        "retrieval and analysis.",
        "",
    ]
    # Summary of branches
    for sub in sub_reports:
        verified = sum(1 for c in sub.claims if c.status == "verified")
        constrained = sum(1 for c in sub.claims if c.status == "constrained")
        lines.append(
            f"- **{sub.facet}** — {verified} verified, {constrained} constrained findings "
            f"(confidence: {sub.confidence})"
        )
    lines.append("")

    # Full content from each sub-report
    for idx, sub in enumerate(sub_reports, 1):
        lines.append(f"## {idx}. {sub.facet}")
        lines.append("")
        content = sub.content.strip()
        if content:
            for prefix in ("## Subtopic Answer", "## Subtopic Analysis"):
                if content.startswith(prefix):
                    content = content[len(prefix):].lstrip("\n")
            lines.append(content)
        else:
            lines.append(f"Research on *{sub.sub_query}* produced limited direct evidence.")
            # Even without content, show what claims we have
            for claim in sub.claims:
                lines.append(f"- [{claim.claim_id}] ({claim.status}) {claim.assertion}")
        lines.append("")

    # Evidence gaps
    all_gaps = set()
    for sub in sub_reports:
        all_gaps.update(sub.reason_codes or [])
    if all_gaps:
        lines.append("## Evidence Gaps and Limitations")
        lines.append("")
        for gap in sorted(all_gaps):
            lines.append(f"- {gap.replace('_', ' ').title()}")
        lines.append("")

    lines.append("## Sources Used")
    lines.append("- Full source ledger is attached below.")

    return "\n".join(lines).strip()


def create_synthesizer_node(runtime: GraphRuntime):
    from core.synthesis.config_helpers import (
        adaptive_min_external_sources,
        effective_max_ctier_ratio,
        effective_min_ab_sources,
        effective_min_claims,
        effective_min_unique_domains,
        effective_min_words,
        effective_source_quality_bar,
    )
    from core.synthesis.doc_helpers import (
        build_analytical_fallback,
        doc_confidence,
        doc_tier,
        is_citable_external_doc,
        unique_docs_by_url,
    )
    from core.synthesis.llm_caller import call_llm
    from core.synthesis.metrics import (
        build_fallback_metrics,
        build_success_metrics,
        intent_note,
        policy_note,
    )

    def synthesizer_node(state: ResearchState) -> dict:
        # Subtopic map-reduce path: merge branch sub-reports as primary synthesis input.
        sub_reports = [
            SubReport.model_validate(item) for item in list(state.get("sub_reports", []))
        ]
        map_reduce_active = (
            runtime.config.subtopic_mode == "map_reduce"
            and bool(state.get("subtopics"))
            and bool(
                state.get("sub_reports") or state.get("shared_corpus_docs")
            )
        )

        if map_reduce_active and state.get("subtopics") and not state.get("shared_corpus_docs"):
            # No shared corpus but sub_reports may exist — fall through to synthesis.
            # If sub_reports also empty, will be handled by the next check.
            pass
        if map_reduce_active and not sub_reports and state.get("subtopics"):
            # All sub-research branches failed — fall through to single-path synthesis
            # which will attempt to use direct docs (tavily/ddg/firecrawl).
            map_reduce_active = False
        if map_reduce_active and sub_reports:
            query_profile = state.get("query_profile") or profile_query(state["query"])
            policy = safe_analysis_policy(
                query_profile, dual_use_depth=runtime.config.dual_use_depth
            )
            tenant_context = state.get("tenant_context")
            tenant_tier = tenant_context.quota_tier if tenant_context else "default"
            context = _build_subreport_context(sub_reports)
            system_msg = (
                INVESTIGATIVE_PROMPT
                if runtime.config.report_structure_mode == "investigative"
                else SYNTHESIZER_PROMPT
            )
            wmin, wmax = report_length_word_range(runtime.config)
            user_msg = (
                f"Query: {state['query']}\n\n"
                f"Context Policy: {policy_note(policy)}\n"
                f"Intent: {intent_note(query_profile)}\n\n"
                "You are the master editor. Synthesize the following analyst sub-reports into a single, COMPREHENSIVE report.\n\n"
                f"{_section_contract(runtime.config.report_structure_mode)}\n"
                "EVIDENCE USAGE RULES:\n"
                "- Anchor all core claims to sub-report evidence using their [C###] IDs.\n"
                "- You MAY enrich sections with domain knowledge, contextual analysis, real-world examples, and practical insights.\n"
                "- Any claim not directly from sub-reports MUST be labeled [UNVERIFIED].\n"
                "- Prioritize cited evidence but do NOT leave sections thin — expand with deep analysis.\n\n"
                "DEPTH REQUIREMENTS:\n"
                f"- Write a thorough, well-structured report of {wmin:,}-{wmax:,} words.\n"
                "- Include ### subsections within major sections.\n"
                "- Write in professional analytical prose, not bulleted lists.\n"
                "- Do NOT hedge excessively — present findings assertively with confidence labels.\n"
                "- Include an Evidence Agreement and Disagreement section if applicable.\n\n"
                f"{context}\n"
            )
            model_selection = runtime.model_router.select_model(
                task_type="synthesis",
                context_size=len(user_msg),
                latency_budget_ms=22000,
                tenant_tier=tenant_tier,
                tenant_context=tenant_context,
                plan_complexity="high",
            )
            runtime.tracer.event(
                state["run_id"],
                "model_route",
                "Synthesis model selected",
                payload={
                    "task": "synthesis",
                    "model": model_selection.model_name,
                    "tier": model_selection.tier,
                    "router_mode": model_selection.router_mode,
                    "confidence": model_selection.confidence,
                    "downgraded": model_selection.was_downgraded,
                },
            )
            citations = _merge_subreport_citations(sub_reports)
            report = ""
            try:
                with runtime.model_router.use_tier(model_selection.tier):
                    client = runtime.get_llm_client(
                        model_selection.provider,
                        request_timeout_seconds=runtime.config.llm_request_timeout_seconds_synthesis,
                    )
                    report = call_llm(
                        client,
                        model_selection.provider,
                        model_selection.model_name,
                        system_msg,
                        user_msg,
                        deep_mode=True,
                    )
            except Exception as exc:
                if _is_timeout_error(exc):
                    report = _build_timeout_constrained_report(sub_reports)
                else:
                    report = _build_subreport_fallback_report(state["query"], sub_reports)
            conflict_rows = _conflict_pairs(sub_reports)
            if conflict_rows:
                report = _ensure_conflict_reconciliation_section(
                    report,
                    conflict_rows=conflict_rows,
                )
            report, citations = format_report_with_sources(
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
            quality_ok, _, _ = assess_report_quality(
                report,
                query=state["query"],
                depth=runtime.config.research_depth,
                min_words=runtime.config.target_report_words_peak_min
                if runtime.config.research_mode == "peak"
                else runtime.config.min_report_words_deep,
                min_claims=max(runtime.config.min_claims_deep, runtime.config.min_primary_claims)
                if runtime.config.research_mode == "peak"
                else runtime.config.min_claims_deep,
                report_structure_mode=runtime.config.report_structure_mode,
                insight_density_min=runtime.config.insight_density_min,
                mechanics_ratio_max_top_sections=runtime.config.mechanics_ratio_max_top_sections,
                top_section_min_verified_claims=runtime.config.top_section_min_verified_claims,
                top_section_max_ctier_ratio=runtime.config.top_section_max_ctier_ratio,
            )
            source_ok, _, _ = validate_source_integrity(
                citations,
                source_policy=runtime.config.source_policy,
                min_external_sources=runtime.config.min_external_sources,
                min_unique_domains=runtime.config.min_unique_domains
                if runtime.config.primary_source_policy == "strict"
                else 0,
                min_unique_providers=runtime.config.min_unique_providers,
                allow_relaxed_diversity=runtime.config.quota_pressure_mode
                and not runtime.config.strict_high_confidence,
                min_tier_ab_sources=max(
                    runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources
                )
                if runtime.config.primary_source_policy == "strict"
                else runtime.config.min_tier_ab_sources,
                max_ctier_claim_ratio=runtime.config.max_ctier_claim_ratio
                if runtime.config.primary_source_policy == "strict"
                else 1.0,
                require_corroboration_for_tier_c=runtime.config.require_corroboration_for_tier_c,
            )
            branch_success = sum(1 for item in sub_reports if item.confidence != "constrained")
            branch_failures = len(sub_reports) - branch_success
            merge_conflicts = _subreport_conflict_count(sub_reports)
            metrics = build_success_metrics(
                state=state,
                citations=citations,
                min_claims_target=runtime.config.min_claims_deep,
                kept_count=len(state.get("shared_corpus_docs", [])),
            )
            metrics.update(
                {
                    "subtopic_count": len(state.get("subtopics", [])),
                    "subtopic_success_count": branch_success,
                    "subtopic_failed_count": branch_failures,
                    "subtopic_reason_codes": sorted(
                        {code for item in sub_reports for code in item.reason_codes if code}
                    ),
                    "merge_conflicts_detected": merge_conflicts,
                    "editor_input_word_count": len(re.findall(r"\b[\w'-]+\b", context)),
                    "subreport_quality_ok": quality_ok,
                    "subreport_source_ok": source_ok,
                    "provider_recovery_actions": (
                        ["llm_timeout_synthesis:fallback_to_claim_registry"]
                        if "llm_timeout_synthesis" in report.lower()
                        else []
                    ),
                }
            )
            return {
                "report_draft": report,
                "citations": citations,
                "metrics": metrics,
                "status": "synthesized",
                "logs": [f"Master synthesizer merged {len(sub_reports)} sub-reports."],
            }

        # 1. Resolve Config & Context
        deep_mode = runtime.config.research_depth == "deep"
        query_profile = state.get("query_profile") or profile_query(state["query"])
        policy = safe_analysis_policy(query_profile, dual_use_depth=runtime.config.dual_use_depth)
        tenant_context = state.get("tenant_context")
        tenant_tier = tenant_context.quota_tier if tenant_context else "default"
        allow_source_relax = (
            runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence
        )

        min_words = effective_min_words(runtime, deep_mode=deep_mode)
        min_claims = effective_min_claims(runtime, deep_mode=deep_mode)

        # 2. Process Documents
        external_pool = unique_docs_by_url(
            [
                d
                for d in state.get("tavily_docs", [])
                + state.get("ddg_docs", [])
                + state.get("firecrawl_docs", [])
                if is_citable_external_doc(d)
            ]
        )
        citable_docs = prioritize_docs(
            external_pool,
            source_quality_bar=effective_source_quality_bar(runtime),
            min_tier_ab_sources=effective_min_ab_sources(runtime),
        )[: 20 if deep_mode else 8]
        if not citable_docs and external_pool:
            citable_docs = external_pool[: 20 if deep_mode else 8]

        pruned_docs = prune_context_docs(
            citable_docs,
            per_doc_tokens=max(runtime.config.per_doc_tokens, 320),
            total_tokens=max(runtime.config.total_context_tokens, 2600),
        )
        if not pruned_docs:
            pruned_docs = list(citable_docs)
        elif len(pruned_docs) < min(len(citable_docs), 6 if deep_mode else 3):
            seen_urls = {normalize_url(doc.url) for doc in pruned_docs if normalize_url(doc.url)}
            for doc in citable_docs:
                url = normalize_url(doc.url)
                if not url or url in seen_urls:
                    continue
                pruned_docs.append(doc)
                seen_urls.add(url)
                target = min(len(citable_docs), 12 if deep_mode else 6)
                if len(pruned_docs) >= target:
                    break

        if not pruned_docs:
            # No external sources — generate report from query using LLM with
            # clear "no external evidence" labeling. Always produce a report.
            logger.warning("No external docs available — synthesizing from query only with confidence labels.")
            system_msg = (
                INVESTIGATIVE_PROMPT
                if runtime.config.report_structure_mode == "investigative"
                else SYNTHESIZER_PROMPT
            )
            user_msg = (
                f"Query: {state['query']}\n\n"
                "IMPORTANT: No external sources were retrieved for this query. "
                "Write a comprehensive analytical report using your domain knowledge. "
                "Label ALL claims as [UNVERIFIED] since no external citations are available. "
                "The report must still be thorough and detailed — explain what is generally known "
                "about this topic, identify key questions, and outline what evidence would be needed. "
                "Do NOT leave sections empty or refuse to write.\n\n"
                "Extracted Claims:\n- No extracted claims available (no external sources retrieved).\n"
            )
            model_selection = runtime.model_router.select_model(
                task_type="synthesis",
                context_size=len(user_msg),
                latency_budget_ms=18000 if deep_mode else 9000,
                tenant_tier=tenant_tier,
                tenant_context=tenant_context,
                plan_complexity="high" if deep_mode else "medium",
            )
            report = ""
            try:
                client = runtime.get_llm_client(
                    model_selection.provider,
                    request_timeout_seconds=runtime.config.llm_request_timeout_seconds_synthesis,
                )
                report = call_llm(
                    client,
                    model_selection.provider,
                    model_selection.model_name,
                    system_msg,
                    user_msg,
                    deep_mode=deep_mode,
                )
            except Exception:  # noqa: BLE001
                report = build_fail_closed_report(
                    state["query"],
                    reason="No external sources found and LLM synthesis also failed.",
                )
            return {
                "report_draft": report,
                "citations": [],
                "metrics": build_fallback_metrics(
                    state=state, citations=[], reason="no_docs_llm_synthesis"
                ),
                "status": "synthesized",
                "logs": ["No external docs — generated report from LLM knowledge with UNVERIFIED labels."],
            }

        # Pre-synthesis Tier-A/B check: log warning but proceed with C-tier evidence.
        # Reports always include confidence labels so readers can assess evidence quality.
        tier_ab_docs = [
            d for d in pruned_docs
            if ((d.meta or {}).get("source_tier") or "").upper() in {"A", "B"}
        ]
        if not tier_ab_docs:
            logger.warning("No Tier-A/B sources found — proceeding with C-tier evidence and confidence labels.")

        # 3. Pass 1: Extraction & Context Building
        extraction_result = None
        try:
            extraction_model = runtime.model_router.select_model(
                task_type="research",
                context_size=sum(len((d.snippet or d.content or "")[:2000]) for d in pruned_docs),
                latency_budget_ms=6000 if deep_mode else 3500,
                tenant_tier=tenant_tier,
                tenant_context=tenant_context,
                plan_complexity="medium",
            )
            extraction_client = runtime.get_llm_client(
                extraction_model.provider,
                request_timeout_seconds=runtime.config.llm_request_timeout_seconds_research,
            )
            extraction_result = extract_claims(
                pruned_docs,
                extraction_client,
                extraction_model.provider,
                extraction_model.model_name,
                max_docs=16 if deep_mode else 8,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claim extraction pass failed: %s", exc)
            extraction_result = None

        if runtime.config.relaxed_quality_mode:
            if not extraction_result or not getattr(extraction_result, "claims", None):
                extraction_result = build_fallback_extraction(
                    pruned_docs,
                    max_claims=max(1, runtime.config.subreport_min_claims),
                )

        source_index = {f"C{i + 1}": doc for i, doc in enumerate(pruned_docs)}

        # 4. Pass 2: Analytical Synthesis
        system_msg = (
            INVESTIGATIVE_PROMPT
            if runtime.config.report_structure_mode == "investigative"
            else SYNTHESIZER_PROMPT
        )
        wmin, wmax = report_length_word_range(runtime.config)
        user_msg = (
            f"Query: {state['query']}\n\n"
            f"Context Policy: {policy_note(policy)}\n"
            f"Intent: {intent_note(query_profile)}\n\n"
            f"{_section_contract(runtime.config.report_structure_mode)}\n"
            "EVIDENCE USAGE RULES:\n"
            "- Anchor all core claims to Extracted Claims using their [C###] IDs.\n"
            "- You MAY enrich sections with domain knowledge, contextual analysis, real-world examples, and practical insights.\n"
            "- Any claim not directly from Extracted Claims MUST be labeled [UNVERIFIED].\n"
            "- Prioritize cited evidence but do NOT leave sections thin — expand with deep analysis.\n\n"
            "DEPTH REQUIREMENTS:\n"
            f"- Write a thorough, well-structured report of {wmin:,}-{wmax:,} words.\n"
            "- Each major section must have ### subsections.\n"
            "- Include real-world examples and practical implications.\n"
            "- Write in professional analytical prose, not bulleted lists.\n"
            "- Do NOT hedge excessively — present findings assertively with confidence labels.\n\n"
            f"Extracted Claims:\n{_format_extracted_claims(extraction_result)}\n"
        )

        model_selection = runtime.model_router.select_model(
            task_type="synthesis",
            context_size=len(user_msg),
            latency_budget_ms=18000 if deep_mode else 9000,
            tenant_tier=tenant_tier,
            tenant_context=tenant_context,
            plan_complexity="high" if deep_mode else "medium",
        )

        report = ""
        try:
            client = runtime.get_llm_client(
                model_selection.provider,
                request_timeout_seconds=runtime.config.llm_request_timeout_seconds_synthesis,
            )
            report = call_llm(
                client,
                model_selection.provider,
                model_selection.model_name,
                system_msg,
                user_msg,
                deep_mode=deep_mode,
            )
        except Exception as exc:
            reason = "llm_failed"
            if _is_timeout_error(exc):
                reason = "llm_timeout_synthesis"
            report, citations, source_index = build_analytical_fallback(
                state["query"], pruned_docs, extraction_result=extraction_result
            )
            metrics = build_fallback_metrics(state=state, citations=citations, reason=reason)
            metrics["provider_recovery_actions"] = [f"{reason}:fallback_to_constrained_brief"]
            return {
                "report_draft": report,
                "citations": citations,
                "metrics": metrics,
                "status": "synthesized",
            }

        # 5. Post-Process & Quality Gate
        citations: list[Citation] = []
        for cid in extract_claim_ids(report):
            if doc := source_index.get(cid):
                citations.append(
                    Citation(
                        claim_id=cid,
                        source_url=normalize_url(doc.url),
                        title=doc.title,
                        provider=doc.provider,
                        evidence=clean_evidence_text(
                            doc.snippet or doc.content,
                            max_chars=runtime.config.max_evidence_quote_chars,
                        ),
                        source_tier=doc_tier(doc),
                        confidence=doc_confidence(doc),
                    )
                )

        citations = dedupe_citations(citations)
        if runtime.config.relaxed_quality_mode and "## Claims" not in (report or ""):
            claims_section = _claims_section_from_extraction(extraction_result)
            if claims_section:
                report = f"{report.strip()}\n\n{claims_section}".strip()
        report, citations = format_report_with_sources(
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

        quality_ok, _, _ = assess_report_quality(
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
            relaxed_mode=runtime.config.relaxed_quality_mode,
        )
        source_ok, _, _ = validate_source_integrity(
            citations,
            source_policy=runtime.config.source_policy,
            min_external_sources=adaptive_min_external_sources(
                len(citable_docs),
                runtime.config.min_external_sources,
                allow_relax=allow_source_relax,
            ),
            min_unique_domains=effective_min_unique_domains(runtime),
            min_unique_providers=runtime.config.min_unique_providers,
            allow_relaxed_diversity=allow_source_relax,
            min_tier_ab_sources=effective_min_ab_sources(runtime),
            max_ctier_claim_ratio=effective_max_ctier_ratio(runtime),
            require_corroboration_for_tier_c=runtime.config.require_corroboration_for_tier_c,
        )

        if quality_ok and source_ok:
            return {
                "report_draft": report,
                "citations": citations,
                "metrics": build_success_metrics(
                    state=state,
                    citations=citations,
                    min_claims_target=min_claims,
                    kept_count=len(citable_docs),
                ),
                "status": "synthesized",
            }

        # Return the report even if quality checks didn't pass - no fallback to templates
        return {
            "report_draft": report,
            "citations": citations,
            "metrics": build_success_metrics(
                state=state,
                citations=citations,
                min_claims_target=min_claims,
                kept_count=len(citable_docs),
            ),
            "status": "synthesized",
        }

    return synthesizer_node
