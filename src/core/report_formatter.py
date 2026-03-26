from __future__ import annotations

import re

from core.citations import dedupe_citations, filter_citations_by_policy, normalize_url
from core.models import Citation

SOURCES_HEADING_PATTERN = re.compile(r"(?ims)^##\s+Sources Used\b")
SECTION_HEADING_PATTERN = re.compile(r"(?m)^#{1,2}\s+(.+)$")

NARRATIVE_SECTION_ORDER = (
    "Executive Summary",
    "Direct Answer",
    "Key Findings",
    "Verified Findings Register",
    "Recommendations",
    "12-Month Action Plan",
    "Risks, Gaps, and Uncertainty",
)

ACADEMIC_17_SECTION_ORDER = (
    "Abstract",
    "Introduction",
    "Theoretical Framework",
    "Literature Review",
    "Hypotheses",
    "Methodology",
    "Metrics & Evaluation",
    "Formal Modeling of Prompting",
    "Empirical Results",
    "Generalization & Scaling Laws",
    "Theoretical Contributions",
    "Practical Contributions",
    "Limitations",
    "Ethical & Governance Considerations",
    "Future Research Directions",
    "Conclusion",
    "Appendices",
)

INVESTIGATIVE_SECTION_ORDER = (
    "Title",
    "Executive Summary",
    "Background and Context",
    "Key Questions",
    "Evidence and Findings",
    "Deep Analysis",
    "Conflicting Evidence",
    "Case Studies or Examples",
    "Limitations of Current Knowledge",
    "Implications",
    "Recommendations",
    "Conclusion",
)

TECHNICAL_SECTION_ORDER = (
    "How This Research Was Done",
    "Evidence Confidence Summary",
    "Scope and Method",
    "Evidence Matrix",
    "Detailed Source Analysis",
    "Counterevidence and Alternative Interpretations",
    "Counterevidence / Alternative Interpretations",  # legacy compat
    "Evidence Agreement and Disagreement",
    "Scenario Outlook",
)


def _claim_sort_key(claim_id: str) -> tuple[int, str]:
    try:
        return (int(claim_id[1:]), claim_id)
    except Exception:  # noqa: BLE001
        return (9999, claim_id)


def _remove_sources_section(report: str) -> str:
    body = (report or "").strip()
    if not body:
        return ""
    match = SOURCES_HEADING_PATTERN.search(body)
    if not match:
        return body
    return body[: match.start()].rstrip()


def _safe_text(value: str, *, max_chars: int) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().replace("|", " "))[:max_chars].strip() or "-"


def _normalize_claim_status_labels(body: str) -> str:
    if not body:
        return ""
    return re.sub(r"(?im)(\|\s*)withheld(\s*\|)", r"\1unverified\2", body)


def _source_type_from_tier(tier: str) -> str:
    normalized = (tier or "unknown").strip().upper()
    if normalized == "A":
        return "Primary"
    if normalized == "B":
        return "Secondary"
    if normalized == "C":
        return "Tertiary"
    return "Unclassified"


def render_sources_snapshot(
    citations: list[Citation],
    *,
    source_policy: str,
    max_sources_snapshot: int = 6,
) -> str:
    filtered = filter_citations_by_policy(citations, source_policy=source_policy)
    if not filtered:
        return (
            "### Sources Snapshot\n"
            "- No qualifying sources available under the active source policy."
        )

    rows: list[str] = ["### Sources Snapshot"]
    for citation in sorted(filtered, key=lambda c: _claim_sort_key(c.claim_id))[
        : max(1, max_sources_snapshot)
    ]:
        url = normalize_url(citation.source_url) or "URL unavailable"
        title = _safe_text(citation.title.strip() or "Untitled source", max_chars=120)
        provider = _safe_text(citation.provider.strip() or "unknown", max_chars=28)
        evidence = _safe_text(citation.evidence, max_chars=180)
        tier = (citation.source_tier or "unknown").upper()
        confidence = (citation.confidence or "unknown").lower()
        rows.extend(
            [
                f"- [{citation.claim_id}] **{title}**",
                f"  - Tier: `{tier}` | Confidence: `{confidence}` | Provider: `{provider}`",
                f"  - URL: {url}",
                f"  - Evidence: {evidence}",
            ]
        )
    if len(filtered) > max_sources_snapshot:
        rows.append(
            f"- ... {len(filtered) - max_sources_snapshot} additional sources are available in the full ledger below."
        )
    return "\n".join(rows)


def _build_sources_block(citations: list[Citation]) -> str:
    if not citations:
        return "No sources available."
    rows = []
    for citation in citations[:15]:
        url = normalize_url(citation.source_url) or "URL unavailable"
        title = citation.title.strip() or "Untitled"
        provider = citation.provider.strip() or "unknown"
        rows.append(f"- **{title}** ({provider}): {url}")
    return "\n".join(rows)


def render_sources_ledger(
    citations: list[Citation],
    *,
    source_policy: str,
    report_structure_mode: str = "decision_brief",
) -> str:
    filtered = filter_citations_by_policy(citations, source_policy=source_policy)
    if report_structure_mode == "investigative":
        rows: list[str] = [
            "### Full Source Ledger (Heuristic Source Types)",
            "_Source Type is inferred heuristically from source tier metadata._",
            "",
        ]
    else:
        rows = [
            "### Full Source Ledger (Detailed Table)",
            "| Claim | Title | Provider | Tier | Confidence | URL | Evidence |",
            "|---|---|---|---|---|---|---|",
        ]
    if not filtered:
        rows.append("No sources available.")
        return "\n".join(rows)

    for citation in sorted(filtered, key=lambda c: _claim_sort_key(c.claim_id)):
        url = normalize_url(citation.source_url) or "URL unavailable"
        title = _safe_text(citation.title.strip() or "Untitled source", max_chars=120)
        provider = _safe_text(citation.provider.strip() or "unknown", max_chars=28)
        evidence = _safe_text(citation.evidence, max_chars=180)
        if report_structure_mode == "investigative":
            source_type = _source_type_from_tier(citation.source_tier or "")
            rows.append(f"- **{title}**")
            rows.append(f"  - Source: {provider}")
            rows.append(f"  - Source Type: {source_type}")
            rows.append(f"  - URL: {url}")
            if evidence:
                rows.append(f"  - Evidence: {evidence}")
            rows.append("")
        else:
            tier = (citation.source_tier or "unknown").upper()
            confidence = (citation.confidence or "unknown").lower()
            rows.append(
                f"| [{citation.claim_id}] | {title} | {provider} | {tier} | {confidence} | {url} | {evidence} |"
            )
    return "\n".join(rows)


def _build_confidence_summary(citations: list[Citation]) -> str:
    tier_a = sum(1 for c in citations if (c.source_tier or "").upper() == "A")
    tier_b = sum(1 for c in citations if (c.source_tier or "").upper() == "B")
    tier_c = sum(1 for c in citations if (c.source_tier or "").upper() == "C")
    high_conf = sum(1 for c in citations if (c.confidence or "").lower() == "high")
    medium_conf = sum(1 for c in citations if (c.confidence or "").lower() == "medium")
    low_conf = sum(1 for c in citations if (c.confidence or "").lower() == "low")
    return (
        "## Evidence Confidence Summary\n"
        f"- Source tiers: A={tier_a}, B={tier_b}, C={tier_c}\n"
        f"- Confidence mix: high={high_conf}, medium={medium_conf}, low={low_conf}\n"
        "- Tier A/B corroboration is prioritized for final conclusions.\n"
        "- Source ledger is split into a readable snapshot plus full audit table."
    )


def _inject_confidence_summary(body: str, citations: list[Citation]) -> str:
    if re.search(r"(?im)^##\s+Evidence Confidence Summary\b", body):
        return body
    summary = _build_confidence_summary(citations)
    return f"{body.strip()}\n\n{summary}".strip()


def _split_sections(body: str) -> list[tuple[str, str]]:
    text = (body or "").strip()
    if not text:
        return []
    matches = list(SECTION_HEADING_PATTERN.finditer(text))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        sections.append((heading, block))
    return sections


def _reorder_sections_for_readability(
    body: str,
    *,
    show_technical_sections_default: bool,
    report_structure_mode: str = "decision_brief",
) -> str:
    sections = _split_sections(body)
    if not sections:
        return body.strip()

    section_map = {heading.lower(): block for heading, block in sections}
    used: set[str] = set()
    reordered: list[str] = []

    def _append_by_heading(heading: str) -> None:
        key = heading.lower()
        block = section_map.get(key)
        if not block or key in used:
            return
        reordered.append(block)
        used.add(key)

    if report_structure_mode == "academic_17":
        ordering = ACADEMIC_17_SECTION_ORDER
    elif report_structure_mode == "investigative":
        ordering = INVESTIGATIVE_SECTION_ORDER
    else:
        ordering = NARRATIVE_SECTION_ORDER
    for heading in ordering:
        _append_by_heading(heading)

    if report_structure_mode == "academic_17":
        for heading, block in sections:
            key = heading.lower()
            if key in used:
                continue
            reordered.append(block)
            used.add(key)
        return "\n\n".join(reordered).strip()

    for heading, block in sections:
        key = heading.lower()
        if key in used:
            continue
        if not show_technical_sections_default and heading in TECHNICAL_SECTION_ORDER:
            continue
        reordered.append(block)
        used.add(key)

    for heading in TECHNICAL_SECTION_ORDER:
        _append_by_heading(heading)

    for heading, block in sections:
        key = heading.lower()
        if key in used:
            continue
        reordered.append(block)
        used.add(key)

    return "\n\n".join(reordered).strip()


def format_report_with_sources(
    report: str,
    citations: list[Citation],
    *,
    source_policy: str,
    report_presentation: str = "book",
    sources_presentation: str = "cards_with_ledger",
    show_technical_sections_default: bool = False,
    report_surface_mode: str = "decision_brief_only",
    report_structure_mode: str = "decision_brief",
    max_sources_snapshot: int = 6,
) -> tuple[str, list[Citation]]:
    cleaned_citations = dedupe_citations(citations)
    body = _remove_sources_section(report)
    body = _normalize_claim_status_labels(body)
    include_confidence_summary = (
        report_surface_mode != "decision_brief_only" or show_technical_sections_default
    )
    if include_confidence_summary and report_structure_mode != "investigative":
        body = _inject_confidence_summary(body, cleaned_citations)
    body = _reorder_sections_for_readability(
        body,
        show_technical_sections_default=(
            show_technical_sections_default or report_surface_mode == "full_technical"
        ),
        report_structure_mode=report_structure_mode,
    )
    snapshot_block = render_sources_snapshot(
        cleaned_citations,
        source_policy=source_policy,
        max_sources_snapshot=max_sources_snapshot,
    )
    ledger_block = render_sources_ledger(
        cleaned_citations,
        source_policy=source_policy,
        report_structure_mode=report_structure_mode,
    )
    if not body:
        body = "## Executive Summary\nNo report body was generated."
    filtered_count = len(filter_citations_by_policy(cleaned_citations, source_policy=source_policy))
    if report_presentation == "standard" or sources_presentation == "ledger_only":
        sources_block = ledger_block
    elif filtered_count <= max_sources_snapshot:
        # Snapshot already covers all sources — no need for a duplicate ledger.
        sources_block = snapshot_block
    else:
        sources_block = f"{snapshot_block}\n\n{ledger_block}"
    formatted = f"{body}\n\n## Sources Used\n{sources_block}"
    return formatted, cleaned_citations


def build_constrained_actionable_report(
    query: str,
    *,
    reason: str,
    reason_codes: list[str] | None = None,
    citations: list[Citation] | None = None,
    report_structure_mode: str = "decision_brief",
) -> str:
    """Generate a report that preserves whatever evidence exists, with confidence labels."""
    cleaned_citations = dedupe_citations(citations or [])
    sources_block = _build_sources_block(cleaned_citations)
    clean_query = (query or "").strip() or "the requested topic"
    constraint_note = f"**Evidence confidence: Constrained** — {reason}" if reason else "**Evidence confidence: Constrained** — limited evidence available."
    codes_note = f"Constraint codes: {', '.join(reason_codes)}" if reason_codes else ""

    if report_structure_mode == "academic_17":
        sections = ACADEMIC_17_SECTION_ORDER
    elif report_structure_mode == "investigative":
        sections = INVESTIGATIVE_SECTION_ORDER
    else:
        sections = NARRATIVE_SECTION_ORDER
    body_parts: list[str] = []
    for heading in sections:
        if heading == "Title":
            body_parts.append(f"# Research Report: {clean_query}")
        elif heading in ("Executive Summary", "Abstract"):
            body_parts.append(
                f"## {heading}\n"
                f"This report examines **{clean_query}** under constrained evidence conditions. "
                f"{constraint_note}\n\n"
                f"{codes_note}\n\n"
                "Findings below use whatever evidence was retrieved, with confidence labels on each claim."
            )
        elif heading == "Conclusion":
            body_parts.append(
                f"## {heading}\n"
                f"The analysis of **{clean_query}** is provisional due to evidence constraints. "
                "All findings should be independently verified before informing decisions. "
                "A re-run with improved source access is recommended."
            )
        else:
            body_parts.append(
                f"## {heading}\n"
                f"{constraint_note} This section requires additional evidence for complete analysis."
            )
    body = "\n\n".join(body_parts).strip()
    return (
        f"{body}\n\n"
        "## Sources Used\n"
        f"{sources_block}\n\n"
        "_Note: Some quality thresholds were not met, but the research findings are preserved above._"
    )


def build_fail_closed_report(
    query: str,
    *,
    reason: str,
) -> str:
    """Generate a best-effort analytical report even when external evidence is limited.

    Instead of returning an empty stub, this produces a structured report that
    acknowledges evidence limitations and labels all claims with confidence
    indicators so the reader can gauge reliability.
    """
    clean_query = (query or "").strip() or "the requested topic"
    reason_line = (reason or "External source retrieval returned limited results.").strip()

    return (
        f"# Research Report: {clean_query}\n\n"
        "## Executive Summary\n"
        f"This report addresses **{clean_query}**. "
        f"**Evidence confidence: Low** — {reason_line} "
        "The analysis below is constructed from the best available information at the time of this run. "
        "All claims are labeled with confidence indicators so the reader can assess reliability.\n\n"
        "Because the external evidence pool was constrained, some sections rely on general domain "
        "knowledge rather than primary sourced citations. Sections that lack external corroboration "
        "are explicitly marked.\n\n"
        "## Background and Context\n"
        f"The research question centers on: **{clean_query}**.\n\n"
        "Understanding this topic requires examining its historical trajectory, the key stakeholders involved, "
        "and the current landscape of debate and evidence. While external retrieval was limited in this run, "
        "the structural context can still be outlined to frame where deeper investigation should focus.\n\n"
        "Context framing is provisional until primary sources confirm the causal links and timelines described. "
        "The reader should treat background claims as **moderate confidence** pending independent verification.\n\n"
        "## Key Questions\n"
        "The following questions guide the analysis:\n\n"
        f"1. What are the core claims and assertions related to **{clean_query}**?\n"
        "2. Which stakeholders or actors are most relevant, and what are their positions?\n"
        "3. Where does the available evidence agree or conflict?\n"
        "4. What data gaps exist that could materially change conclusions?\n"
        "5. What practical implications follow from the strongest available evidence?\n\n"
        "These questions structure the report sections below. Each finding is annotated with its "
        "evidence strength.\n\n"
        "## Evidence and Findings\n"
        f"**Evidence confidence: Low** — Source retrieval was constrained ({reason_line}).\n\n"
        "No externally sourced claim citations are available for this section. The findings below "
        "are based on general domain knowledge and should be independently verified:\n\n"
        f"- The topic of **{clean_query}** intersects with multiple domains that require primary source evidence.\n"
        "- Without corroborated external sources, specific quantitative findings cannot be stated.\n"
        "- The research question is well-formed and investigable — a retry with improved source access "
        "should yield substantive cited findings.\n\n"
        "**Recommendation**: Re-run this query after verifying API keys and provider connectivity.\n\n"
        "## Deep Analysis\n"
        "Detailed analytical interpretation is limited without a sufficient evidence base. "
        "The following structural analysis is offered:\n\n"
        "- **Causal pathways**: The mechanisms connecting key variables in this domain "
        "typically involve multiple mediating factors that require primary evidence to map.\n"
        "- **Stakeholder dynamics**: Identifying which actors drive outcomes requires sourced "
        "documentation of positions, actions, and stated objectives.\n"
        "- **Trend analysis**: Temporal patterns and trajectories need dated evidence points "
        "to establish direction and magnitude of change.\n\n"
        "Each of these analytical dimensions should be populated with cited evidence in a "
        "full-evidence run.\n\n"
        "## Conflicting Evidence\n"
        "No conflicting evidence was identified because the source pool was insufficient. "
        "In a full run, this section compares opposing claims, evaluates the credibility of "
        "each source, and explains which interpretation is better supported and why.\n\n"
        "## Case Studies or Examples\n"
        "Case studies require concrete, sourced examples with dates, actors, and measured outcomes. "
        "This section is reserved for a follow-up run with expanded source access.\n\n"
        "## Limitations of Current Knowledge\n"
        f"- **Primary limitation**: {reason_line}\n"
        "- The report lacks externally cited claims, meaning all analytical conclusions are provisional.\n"
        "- Source tier distribution is unavailable (no Tier-A, B, or C sources were retrieved).\n"
        "- The confidence floor for this report is **low** across all sections.\n\n"
        "## Implications\n"
        "Based on the structural analysis above, the following provisional implications are noted:\n\n"
        f"- The topic of **{clean_query}** warrants deeper investigation with improved source access.\n"
        "- Decision-makers should not act on the findings in this report without independent verification.\n"
        "- A re-run with corrected provider configuration should substantially improve evidence density.\n\n"
        "## Recommendations\n"
        "1. **Verify provider connectivity**: Ensure API keys for search providers (Tavily, DDG) are valid.\n"
        "2. **Retry the query**: Source availability can vary; a subsequent run may retrieve more evidence.\n"
        "3. **Refine the query**: Adding specific constraints (timeframe, region, metric) can improve retrieval quality.\n"
        "4. **Cross-reference independently**: Use the Key Questions section as a checklist for manual verification.\n\n"
        "## Conclusion\n"
        f"This report on **{clean_query}** was produced under evidence-constrained conditions. "
        "While the structural framework and analytical approach are sound, the absence of externally "
        "cited sources means all findings carry low confidence. The report is designed to be immediately "
        "useful as a framework for further investigation rather than a definitive analysis.\n\n"
        "## Sources Used\n"
        "No qualifying external sources were retrieved in this run.\n"
    )
