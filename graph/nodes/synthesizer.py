"""synthesizer.py — Orchestrates the Pass 2 Analytical Synthesis of the research report.

This node is a thin orchestrator that leverages core.synthesis modules to handle
doc processing, config thresholds, LLM calls, and metrics assembly.
"""
from __future__ import annotations

import logging
import re

from agents.prompts import SYNTHESIZER_PROMPT
from core.citations import (
    dedupe_citations,
    extract_claim_ids,
    normalize_url,
    validate_source_integrity,
)
from core.claim_extractor import extract_claims
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
        excerpt = evidence[:180] if evidence else "No excerpt provided."
        lines.append(
            f"- [{source_id}] ({topic}, {strength}) {assertion}\n  Evidence: {excerpt}"
        )
    return "\n".join(lines) if lines else "- No extracted claims available."


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
    return (
        "Required top order: Executive Summary, Direct Answer, Key Findings, "
        "Verified Findings Register, Recommendations, 12-Month Action Plan."
    )


def _build_subreport_fallback_report(query: str, sub_reports: list[SubReport]) -> str:
    lines = [
        "## Executive Summary",
        f"This report synthesizes {len(sub_reports)} parallel sub-research analyses for the query.",
        "",
        "## Direct Answer",
        "Verified: branch findings with corroborated support are retained as decision inputs.",
        "Constrained: branch findings with missing corroboration/proof fields are directional only.",
        "Unknowns: unresolved branch gaps are listed in evidence gaps and reason codes.",
        "",
        "## Key Findings",
    ]
    for sub_report in sub_reports:
        lines.append(
            f"- **{sub_report.facet}** ({sub_report.confidence}): "
            f"{sub_report.content.splitlines()[1] if len(sub_report.content.splitlines()) > 1 else sub_report.sub_query}"
        )
    lines.extend(
        [
            "",
            "## Verified Findings Register",
            "| Claim ID | Status | Why | Evidence Summary | Sources |",
            "|---|---|---|---|---|",
        ]
    )
    for sub_report in sub_reports:
        for claim in sub_report.claims:
            citation = next((c for c in sub_report.citations if c.claim_id == claim.claim_id), None)
            reason = ", ".join(claim.reason_codes) if claim.reason_codes else "Sufficient corroboration"
            evidence = (claim.evidence or (citation.evidence if citation else "") or "").replace("|", " ")
            source_url = citation.source_url if citation else "-"
            lines.append(
                f"| [{claim.claim_id}] | {claim.status} | {reason} | {evidence[:160]} | {source_url} |"
            )
    lines.extend(
        [
            "",
            "## Recommendations",
            "- Prioritize actions backed by verified findings across multiple subtopics.",
            "- Treat constrained findings as hypotheses pending additional corroboration.",
            "",
            "## 12-Month Action Plan",
            "- Q1: Close highest-impact evidence gaps and strengthen corroboration.",
            "- Q2: Re-run targeted retrieval for constrained subtopics.",
            "- Q3: Validate contradictions and update operating guidance.",
            "- Q4: Institutionalize quarterly refresh and drift checks.",
            "",
            "## Risks, Gaps, and Uncertainty",
            "- Branch-level constrained claims indicate incomplete evidence in some facets.",
            "",
            "## Sources Used",
            "- Full source ledger is attached below.",
        ]
    )
    return "\n".join(lines).strip()


def _build_timeout_constrained_report(sub_reports: list[SubReport]) -> str:
    verified = []
    constrained = []
    unknowns = []
    register_rows = [
        "| Claim ID | Status | Why | Evidence Summary | Sources |",
        "|---|---|---|---|---|",
    ]
    for sub_report in sub_reports:
        cite_by_id = {item.claim_id: item for item in sub_report.citations}
        for claim in sub_report.claims:
            citation = cite_by_id.get(claim.claim_id)
            evidence = (claim.evidence or (citation.evidence if citation else "") or "").replace("|", " ")
            source_url = citation.source_url if citation else "-"
            reasons = ", ".join(claim.reason_codes) if claim.reason_codes else "sufficient_support"
            register_rows.append(
                f"| [{claim.claim_id}] | {claim.status} | {reasons} | {evidence[:150]} | {source_url} |"
            )
            entry = f"[{claim.claim_id}] {claim.assertion}"
            if claim.status == "verified":
                verified.append(entry)
            elif claim.status == "constrained":
                constrained.append(entry)
            else:
                unknowns.append(entry)
    if not unknowns:
        unknowns = [
            "Master synthesis timed out before full editorial merge; unresolved narrative conflicts remain unknown.",
        ]
    if len(register_rows) == 2:
        register_rows.append(
            "| - | constrained | llm_timeout_synthesis | No claim registry rows available from branch output | - |"
        )
    lines = [
        "## Executive Summary",
        "Master synthesis timed out; this report provides a constrained decision brief built only from branch claim records.",
        "",
        "## Direct Answer",
        "Verified: " + ("; ".join(verified[:4]) if verified else "No verified conclusions passed the current floor."),
        "Constrained: " + ("; ".join(constrained[:4]) if constrained else "No constrained findings were retained."),
        "Unknowns: " + ("; ".join(unknowns[:3]) if unknowns else "None."),
        "",
        "## Key Findings",
        f"- Subtopic branches completed: {len(sub_reports)}.",
        f"- Verified findings retained: {len(verified)}.",
        f"- Constrained findings retained: {len(constrained)}.",
        "",
        "## Verified Findings Register",
        *register_rows,
        "",
        "## Recommendations",
        "- Re-run synthesis to produce full editorial narrative once provider latency stabilizes.",
        "- Prioritize verified findings for immediate decisions and treat constrained findings as directional.",
        "",
        "## 12-Month Action Plan",
        "- Q1: Stabilize synthesis runtime and provider latency.",
        "- Q2: Re-run constrained branches with stronger primary-source corroboration.",
        "- Q3: Resolve contradiction pairs and refresh verification counts.",
        "- Q4: Automate regression checks for timeout and report-quality gates.",
        "",
        "## Risks, Gaps, and Uncertainty",
        "- `llm_timeout_synthesis` limited narrative depth in this run.",
    ]
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
        sub_reports = [SubReport.model_validate(item) for item in list(state.get("sub_reports", []))]
        map_reduce_active = runtime.config.subtopic_mode == "map_reduce" and bool(
            state.get("subtopics") or state.get("sub_reports") or state.get("shared_corpus_docs")
        )

        if map_reduce_active and state.get("subtopics") and not state.get("shared_corpus_docs"):
            report = build_fail_closed_report(
                state["query"],
                reason="No citable external sources were retrieved.",
            )
            return {
                "report_draft": report,
                "citations": [],
                "metrics": build_fallback_metrics(
                    state=state,
                    citations=[],
                    reason="no_docs",
                    kept_count=0,
                ),
                "status": "synthesized",
                "logs": ["Map-reduce failed-closed: shared corpus is empty."],
            }
        if map_reduce_active and not sub_reports and state.get("subtopics"):
            report = build_fail_closed_report(
                state["query"],
                reason="All sub-research branches failed before synthesis.",
            )
            return {
                "report_draft": report,
                "citations": [],
                "metrics": build_fallback_metrics(
                    state=state,
                    citations=[],
                    reason="all_subtopics_failed",
                    kept_count=len(state.get("shared_corpus_docs", [])),
                ),
                "status": "synthesized",
                "logs": ["All subtopic branches failed; generated fail-closed draft."],
            }
        if map_reduce_active and sub_reports:
            query_profile = state.get("query_profile") or profile_query(state["query"])
            policy = safe_analysis_policy(query_profile, dual_use_depth=runtime.config.dual_use_depth)
            tenant_context = state.get("tenant_context")
            tenant_tier = tenant_context.quota_tier if tenant_context else "default"
            context = _build_subreport_context(sub_reports)
            system_msg = SYNTHESIZER_PROMPT
            user_msg = (
                f"Query: {state['query']}\n\n"
                f"Context Policy: {policy_note(policy)}\n"
                f"Intent: {intent_note(query_profile)}\n\n"
                "You are the master editor. Merge only the following analyst sub-reports.\n"
                "Do not introduce facts outside this input.\n\n"
                f"{_section_contract(runtime.config.report_structure_mode)}\n"
                "Include an explicit `Evidence Agreement and Disagreement` section.\n\n"
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
            citations = _merge_subreport_citations(sub_reports)
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
                    deep_mode=True,
                )
            except Exception as exc:
                if _is_timeout_error(exc):
                    report = _build_timeout_constrained_report(sub_reports)
                else:
                    report, citations, _ = build_analytical_fallback(
                        state["query"],
                        list(state.get("shared_corpus_docs", [])),
                    )
            if not citations:
                _, citations, _ = build_analytical_fallback(
                    state["query"],
                    list(state.get("shared_corpus_docs", [])),
                )
            conflict_rows = _conflict_pairs(sub_reports)
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
                allow_relaxed_diversity=runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence,
                min_tier_ab_sources=max(runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources)
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
                        {
                            code
                            for item in sub_reports
                            for code in item.reason_codes
                            if code
                        }
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
                "logs": [
                    f"Master synthesizer merged {len(sub_reports)} sub-reports."
                ],
            }

        # 1. Resolve Config & Context
        deep_mode = runtime.config.research_depth == "deep"
        query_profile = state.get("query_profile") or profile_query(state["query"])
        policy = safe_analysis_policy(query_profile, dual_use_depth=runtime.config.dual_use_depth)
        tenant_context = state.get("tenant_context")
        tenant_tier = tenant_context.quota_tier if tenant_context else "default"
        allow_source_relax = runtime.config.quota_pressure_mode and not runtime.config.strict_high_confidence

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
            report, citations, source_index = build_analytical_fallback(state["query"], [])
            return {"report_draft": report, "citations": citations, "metrics": build_fallback_metrics(state=state, citations=citations, reason="no_docs"), "status": "synthesized"}

        # 3. Pass 1: Extraction & Context Building
        extraction_result = None
        try:
            extraction_model = runtime.model_router.select_model(
                task_type="research",
                context_size=sum(len((d.snippet or d.content or "")[:400]) for d in pruned_docs),
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

        source_index = {f"C{i+1}": doc for i, doc in enumerate(pruned_docs)}

        # 4. Pass 2: Analytical Synthesis
        system_msg = SYNTHESIZER_PROMPT
        user_msg = (
            f"Query: {state['query']}\n\n"
            f"Context Policy: {policy_note(policy)}\n"
            f"Intent: {intent_note(query_profile)}\n\n"
            f"{_section_contract(runtime.config.report_structure_mode)}\n"
            "No-new-facts rule: use only evidence present in Extracted Claims.\n\n"
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
            report = call_llm(client, model_selection.provider, model_selection.model_name, system_msg, user_msg, deep_mode=deep_mode)
        except Exception as exc:
            reason = "llm_failed"
            if _is_timeout_error(exc):
                reason = "llm_timeout_synthesis"
            report, citations, source_index = build_analytical_fallback(state["query"], pruned_docs, extraction_result=extraction_result)
            metrics = build_fallback_metrics(state=state, citations=citations, reason=reason)
            metrics["provider_recovery_actions"] = [f"{reason}:fallback_to_constrained_brief"]
            return {"report_draft": report, "citations": citations, "metrics": metrics, "status": "synthesized"}

        # 5. Post-Process & Quality Gate
        citations: list[Citation] = []
        for cid in extract_claim_ids(report):
            if doc := source_index.get(cid):
                citations.append(Citation(claim_id=cid, source_url=normalize_url(doc.url), title=doc.title, provider=doc.provider, evidence=clean_evidence_text(doc.snippet or doc.content, max_chars=runtime.config.max_evidence_quote_chars), source_tier=doc_tier(doc), confidence=doc_confidence(doc)))

        citations = dedupe_citations(citations)
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

        # 6. Final Fallback
        report, citations, source_index = build_analytical_fallback(state["query"], pruned_docs, extraction_result=extraction_result)
        return {
            "report_draft": report,
            "citations": citations,
            "metrics": build_fallback_metrics(
                state=state,
                citations=citations,
                reason="quality_failed",
                kept_count=len(citable_docs),
            ),
            "status": "synthesized",
        }

    return synthesizer_node
