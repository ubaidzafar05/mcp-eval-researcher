from __future__ import annotations

import re

from core.citations import dedupe_citations, filter_citations_by_policy, normalize_url
from core.models import Citation

SOURCES_HEADING_PATTERN = re.compile(r"(?ims)^##\s+Sources Used\b")
SECTION_HEADING_PATTERN = re.compile(r"(?m)^##\s+(.+)$")

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
    for citation in sorted(filtered, key=lambda c: _claim_sort_key(c.claim_id))[: max(1, max_sources_snapshot)]:
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

def render_sources_ledger(
    citations: list[Citation],
    *,
    source_policy: str,
) -> str:
    filtered = filter_citations_by_policy(citations, source_policy=source_policy)
    rows: list[str] = [
        "### Full Source Ledger (Detailed Table)",
        "| Claim | Title | Provider | Tier | Confidence | URL | Evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    if not filtered:
        rows.append("| - | No qualifying sources available | - | - | - | - | - |")
        return "\n".join(rows)

    for citation in sorted(filtered, key=lambda c: _claim_sort_key(c.claim_id)):
        url = normalize_url(citation.source_url) or "URL unavailable"
        title = _safe_text(citation.title.strip() or "Untitled source", max_chars=120)
        provider = _safe_text(citation.provider.strip() or "unknown", max_chars=28)
        evidence = _safe_text(citation.evidence, max_chars=180)
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

    ordering = ACADEMIC_17_SECTION_ORDER if report_structure_mode == "academic_17" else NARRATIVE_SECTION_ORDER
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
    include_confidence_summary = (
        report_surface_mode != "decision_brief_only"
        or show_technical_sections_default
    )
    if include_confidence_summary:
        body = _inject_confidence_summary(body, cleaned_citations)
    body = _reorder_sections_for_readability(
        body,
        show_technical_sections_default=(
            show_technical_sections_default
            or report_surface_mode == "full_technical"
        ),
        report_structure_mode=report_structure_mode,
    )
    snapshot_block = render_sources_snapshot(
        cleaned_citations,
        source_policy=source_policy,
        max_sources_snapshot=max_sources_snapshot,
    )
    ledger_block = render_sources_ledger(cleaned_citations, source_policy=source_policy)
    if not body:
        body = "## Executive Summary\nNo report body was generated."
    if report_presentation == "standard" or sources_presentation == "ledger_only":
        sources_block = ledger_block
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
    reason_codes = [code for code in (reason_codes or []) if code]
    reasons_line = ", ".join(reason_codes) if reason_codes else "verification_floor"
    cleaned_citations = dedupe_citations(citations or [])
    register_rows: list[str] = []
    for citation in cleaned_citations[:8]:
        evidence = _safe_text(citation.evidence, max_chars=150)
        title = _safe_text(citation.title, max_chars=100)
        url = normalize_url(citation.source_url) or "URL unavailable"
        register_rows.append(
            f"| [{citation.claim_id}] | constrained | Missing verification floor (`{reasons_line}`) | {evidence} | {title} ({url}) |"
        )
    if not register_rows:
        register_rows.append(
            "| - | constrained | Verification floor not fully met | Additional primary/corroborated evidence required before assertion | See Sources Used |"
        )
    if report_structure_mode == "academic_17":
        evidence_snapshot = "\n".join(
            f"- [{c.claim_id}] {(_safe_text(c.title, max_chars=90) or 'Untitled')} | {normalize_url(c.source_url) or 'URL unavailable'}"
            for c in cleaned_citations[:8]
        ) or "- No citable evidence rows passed strict filters."
        return (
            "## Abstract\n"
            "This constrained academic report presents the verified subset of evidence, explicitly marks uncertain claims, and avoids unsupported conclusions.\n\n"
            "## Introduction\n"
            f"Research question: {query}\n"
            "The current run is constrained by verification coverage and/or provider quality limits.\n\n"
            "## Theoretical Framework\n"
            "Inference is restricted to citation-backed claim records; unsupported extrapolation is excluded by design.\n\n"
            "## Literature Review\n"
            "Available sources were tier-weighted and checked for corroboration depth before promotion to verified status.\n\n"
            "## Hypotheses\n"
            "- H1: Some conclusions are verifiable under current evidence.\n"
            "- H2: Key decisions remain constrained until missing proof fields are resolved.\n\n"
            "## Methodology\n"
            "- Multi-provider retrieval, claim extraction, and strict verification gate.\n"
            "- Missing proof fields are captured as explicit constrained reasons.\n\n"
            "## Metrics & Evaluation\n"
            f"- Constrained reason codes: {reasons_line}\n"
            f"- Candidate citations retained: {len(cleaned_citations)}\n\n"
            "## Formal Modeling of Prompting\n"
            "Prompt/synthesis behavior was bounded to claim records to reduce hallucination risk in constrained conditions.\n\n"
            "## Empirical Results\n"
            "Verified findings are limited; constrained findings dominate this run due to unmet proof floors.\n\n"
            "## Generalization & Scaling Laws\n"
            "Generalization remains limited under constrained evidence; reruns with higher-quality sources are required.\n\n"
            "## Theoretical Contributions\n"
            "Primary contribution in this run is transparent uncertainty handling and strict claim demotion.\n\n"
            "## Practical Contributions\n"
            "- Immediate decisions can use only verified rows.\n"
            "- Constrained rows define concrete next retrieval actions.\n\n"
            "## Limitations\n"
            f"- {reason}\n"
            "- Missing corroboration/open-status/deadline fields block stronger conclusions.\n\n"
            "## Ethical & Governance Considerations\n"
            "The report intentionally avoids overclaiming and labels uncertainty before decision use.\n\n"
            "## Future Research Directions\n"
            "- Expand primary-source coverage.\n"
            "- Increase provider diversity.\n"
            "- Re-run contradiction checks after evidence refresh.\n\n"
            "## Conclusion\n"
            "This run is decision-useful only for verified subset claims; unresolved fields must be closed before high-impact action.\n\n"
            "## Appendices\n"
            "### Missing Proof Fields and Actions\n"
            f"- Active constraints: {reasons_line}\n"
            "- Next action 1: collect primary/official corroboration for constrained claims.\n"
            "- Next action 2: validate recency/deadline fields where required.\n"
            "- Next action 3: rerun with expanded provider capacity.\n\n"
            "### Verified Findings Register\n"
            "| Claim ID | Status | Why | Evidence Summary | Sources |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(register_rows)
            + "\n\n### Evidence Snapshot\n"
            + evidence_snapshot
            + "\n\n## Sources Used\n"
            "- Source ledger appended below."
        )

    return (
        "## Executive Summary\n"
        "This run produced a constrained decision brief. A subset of evidence is usable, but key claims remain unverified under strict proof rules.\n\n"
        "## Direct Answer\n"
        "Verified: only claims with primary or cross-source corroborated support should be treated as decision inputs.\n"
        "Constrained: claims missing corroboration, open-status proof, or primary evidence are directional only.\n"
        "Unknowns: unresolved fields are listed below and must be validated before irreversible decisions.\n\n"
        "## Key Findings\n"
        f"- Current run constraint: {reason}\n"
        f"- Triggered checks: {reasons_line}\n"
        "- Final conclusions are intentionally narrowed to avoid overclaiming.\n\n"
        "## Verified Findings Register\n"
        "| Claim ID | Status | Why | Evidence Summary | Sources |\n"
        "|---|---|---|---|---|\n"
        + "\n".join(register_rows)
        + "\n\n"
        "## Recommendations\n"
        "- Re-run with stronger primary sources and at least two independent providers.\n"
        "- For opportunity/availability queries, capture explicit open status, cycle date, deadline, and eligibility proof.\n"
        "- Keep decisions provisional until constrained fields are resolved.\n\n"
        "## 12-Month Action Plan\n"
        "- Q1: Close missing proof fields and re-run with strict recency checks.\n"
        "- Q2: Expand provider/domain diversity and enforce verification floors.\n"
        "- Q3: Run contradiction checks and downgrade unsupported claims.\n"
        "- Q4: Operationalize recurring quality audits for report reliability.\n\n"
        "## Risks, Gaps, and Uncertainty\n"
        f"- {reason}\n"
        "- Missing proof fields prevent high-confidence assertions in this run.\n\n"
        "## Sources Used\n"
        "- Source ledger appended below."
    )


def build_fail_closed_report(
    query: str,
    *,
    reason: str,
) -> str:
    return (
        "## Executive Summary\n"
        "Insufficient external evidence is available to produce a reliable deep-research report.\n\n"
        "## Direct Answer\n"
        "A confident answer cannot be provided under strict source policy because qualifying evidence did not pass integrity thresholds.\n\n"
        "## Key Findings\n"
        "- No factual findings are provided because source integrity requirements were not met.\n\n"
        "## Recommendations\n"
        "- Retry with a narrower query and explicit high-confidence domains (standards/research institutions).\n"
        "- Confirm Tavily/DDG/Firecrawl connectivity and quotas.\n"
        "- Re-run before using results in decisions.\n"
        "- Prefer primary technical docs or peer-reviewed sources for this topic.\n\n"
        "## 12-Month Action Plan\n"
        "- Q1: Restore provider reliability and validate API keys and quotas.\n"
        "- Q2: Run recurring evidence-integrity checks and source diversity monitoring.\n"
        "- Q3: Calibrate retrieval breadth and pruning budgets for stable deep outputs.\n"
        "- Q4: Maintain monthly production smoke tests for source integrity and report depth.\n\n"
        "## How This Research Was Done\n"
        "- Attempted external retrieval and source normalization across configured providers.\n"
        "- Applied strict source-quality thresholds and URL-backed citation integrity checks.\n"
        "- Stopped synthesis before factual conclusions because evidence quality was insufficient.\n\n"
        "## Evidence Confidence Summary\n"
        "- Source tiers: A=0, B=0, C=0\n"
        "- Confidence mix: high=0, medium=0, low=0\n"
        "- Report is fail-closed due to insufficient qualifying evidence.\n\n"
        "## Scope and Method\n"
        f"- Query: **{query}**\n"
        "- Source policy: external_only\n"
        "- Mode: fail_closed\n"
        "- Method: report generation stopped before factual synthesis.\n\n"
        "## Evidence Matrix\n"
        "- No externally citable sources were available for claim construction.\n\n"
        "## Detailed Source Analysis\n"
        "- Not available because no qualifying external sources were retrieved.\n\n"
        "## Counterevidence / Alternative Interpretations\n"
        "- Not applicable due to lack of qualified sources.\n\n"
        "## Evidence Agreement and Disagreement\n"
        "- Contradiction scan skipped because no qualifying sources were available.\n\n"
        "## Scenario Outlook\n"
        "- Base case: rerun with broader retrieval and verified providers.\n"
        "- Upside case: retrieval succeeds with 5+ qualified external sources.\n"
        "- Downside case: persistent quota/network failures continue to block evidence collection.\n\n"
        "## Risks, Gaps, and Uncertainty\n"
        f"- {reason}\n"
        "- Any narrative answer would risk unsupported claims.\n\n"
        "## Sources Used\n"
        "- No qualifying external sources available."
    )
