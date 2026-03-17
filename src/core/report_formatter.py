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
        rows: list[str] = []
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
            rows.append(f"- **{title}**")
            rows.append(f"  - Source: {provider}")
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
    cleaned_citations = dedupe_citations(citations or [])
    sources_block = _build_sources_block(cleaned_citations)
    constraint_line = f"Constrained due to: {reason}" if reason else "Constrained due to missing evidence."
    if report_structure_mode == "academic_17":
        sections = ACADEMIC_17_SECTION_ORDER
    elif report_structure_mode == "investigative":
        sections = INVESTIGATIVE_SECTION_ORDER
    else:
        sections = NARRATIVE_SECTION_ORDER
    body_parts: list[str] = []
    for heading in sections:
        if heading == "Title":
            body_parts.append(f"# {query}")
        else:
            body_parts.append(f"## {heading}\n{constraint_line}")
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
    return (
        "## Executive Summary\n"
        "Unable to generate a complete research report due to insufficient external evidence.\n"
        "Insufficient external evidence prevents verified conclusions.\n\n"
        "No factual findings are provided.\n\n"
        "## How This Research Was Done\n"
        "The system attempted external retrieval under the configured source policy, but did not obtain\n"
        "enough qualifying evidence to support verified conclusions.\n\n"
        "## Detailed Source Analysis\n"
        "No qualifying sources were available for detailed analysis under the current policy.\n\n"
        "## Scenario Outlook\n"
        "Scenario analysis is not available without sufficient external evidence.\n\n"
        "## 12-Month Action Plan\n"
        "Action planning is deferred until credible external sources are available.\n\n"
        "## Sources Used\n"
        "No qualifying external sources were available for this query.\n\n"
        "## Recommendations\n"
        "- Try a more specific query\n"
        "- Verify API keys and connectivity\n"
        "- Retry later when more sources may be available\n"
    )
