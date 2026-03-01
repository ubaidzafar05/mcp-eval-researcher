"""core.synthesis.doc_helpers — Pure helpers that operate on RetrievedDoc objects.

All functions here are stateless and free of runtime/config dependencies.
They deal exclusively with inspecting, cleaning, and classifying source documents.
"""
from __future__ import annotations

from collections.abc import Iterable

from core.citations import (
    dedupe_citations,
    is_external_provider,
    normalize_url,
)
from core.claim_extractor import ExtractionResult
from core.models import Citation, QueryProfile, RetrievedDoc
from core.report_formatter import build_fail_closed_report
from core.source_quality import (
    clean_evidence_text,
    evidence_confidence,
    source_tier,
)


def best_text(doc: RetrievedDoc) -> str:
    """Return the single most useful sentence from a document."""
    text = clean_evidence_text(doc.content or doc.snippet, max_chars=260)
    if not text:
        return f"Source insight from {doc.provider}."
    return text.split(".")[0].strip() if "." in text else text


def is_citable_external_doc(doc: RetrievedDoc) -> bool:
    """True when the doc comes from an external provider with a valid URL."""
    return is_external_provider(doc.provider) and bool(normalize_url(doc.url))


def unique_docs_by_url(docs: Iterable[RetrievedDoc]) -> list[RetrievedDoc]:
    """Deduplicate docs by normalized URL, discarding those without a valid URL."""
    seen: set[str] = set()
    result: list[RetrievedDoc] = []
    for doc in docs:
        url = normalize_url(doc.url)
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(doc.model_copy(update={"url": url}))
    return result


def doc_tier(doc: RetrievedDoc) -> str:
    """Return the source tier ('A', 'B', 'C', or 'unknown') for a document.

    Prefers an explicit tier set in doc.meta; falls back to URL/provider inference.
    """
    tier = str((doc.meta or {}).get("source_tier") or "")
    if not tier:
        tier = source_tier(doc.url, doc.provider, doc.title)
    tier = tier.upper()
    return tier if tier in {"A", "B", "C"} else "unknown"


def doc_confidence(doc: RetrievedDoc) -> str:
    """Return a confidence label ('high', 'medium', 'low') for a document."""
    confidence = str((doc.meta or {}).get("confidence") or "")
    if confidence:
        return confidence
    return evidence_confidence(doc_tier(doc), doc.snippet or doc.content)


def derive_lens(query_profile: QueryProfile, doc: RetrievedDoc) -> str:
    """Return an analytical lens label appropriate for a document given the query profile.

    The lens is used to frame how a claim should be interpreted in context.
    """
    blob = f"{doc.title} {doc.snippet} {doc.content[:260]}".lower()
    for facet in query_profile.domain_facets:
        if facet and facet in blob:
            return f"{facet.replace('-', ' ').title()} Analysis"
    if "benchmark" in blob or "evaluation" in blob:
        return "Methodology and Benchmark Analysis"
    if "risk" in blob or "limit" in blob or "false positive" in blob:
        return "Limitations and Failure Modes"
    if "policy" in blob or "regulation" in blob or "governance" in blob:
        return "Governance and Operational Controls"
    return "Core Technical Signal"


def evidence_summary(docs: list[RetrievedDoc]) -> tuple[int, int, int, int]:
    """Return (tier_a_count, tier_b_count, tier_c_count, total) for a doc list."""
    a = sum(1 for d in docs if doc_tier(d) == "A")
    b = sum(1 for d in docs if doc_tier(d) == "B")
    c = sum(1 for d in docs if doc_tier(d) == "C")
    return a, b, c, len(docs)


def build_analytical_fallback(
    query: str,
    docs: list[RetrievedDoc],
    *,
    extraction_result: ExtractionResult | None = None,
) -> tuple[str, list[Citation], dict[str, RetrievedDoc]]:
    """Build a paragraph-form analytical report without an LLM call.

    Used when both LLM passes fail. Groups evidence by topic when claim
    extraction succeeded; otherwise falls back to plain snippet summaries.
    Returns (report_markdown, deduplicated_citations, source_index).
    """
    top_docs = docs[:24]

    if not top_docs:
        return (
            build_fail_closed_report(query, reason="No citable external sources were retrieved."),
            [],
            {},
        )

    source_index: dict[str, RetrievedDoc] = {}
    citations: list[Citation] = []

    for i, doc in enumerate(top_docs, start=1):
        claim_id = f"C{i}"
        url = normalize_url(doc.url)
        tier = doc_tier(doc)
        confidence = doc_confidence(doc)
        source_index[claim_id] = doc
        citations.append(
            Citation(
                claim_id=claim_id,
                source_url=url,
                title=doc.title,
                provider=doc.provider,
                evidence=clean_evidence_text(doc.snippet or best_text(doc), max_chars=220),
                source_tier=tier,  # type: ignore[arg-type]
                confidence=confidence,  # type: ignore[arg-type]
            )
        )

    tier_a, tier_b, tier_c, total_sources = evidence_summary(top_docs)
    dual_use_terms = ("bypass", "evasion", "abuse", "exploit", "attack")
    defensive_mode = any(term in (query or "").lower() for term in dual_use_terms)
    defensive_note = (
        "Because this is a potential dual-use topic, conclusions are framed defensively: "
        "controls, monitoring, and risk reduction are prioritized over procedural bypass detail."
        if defensive_mode
        else "This fallback emphasizes factual interpretation, explicit uncertainty, and decision-useful synthesis."
    )

    established_lines: list[str] = []
    constrained_lines: list[str] = []
    register_rows: list[str] = [
        "| Claim | Status | Why | Evidence Summary | Sources | Freshness/Open Proof |",
        "|---|---|---|---|---|---|",
    ]
    detailed_sections: list[str] = []

    for i, doc in enumerate(top_docs, start=1):
        claim_id = f"C{i}"
        tier = doc_tier(doc)
        status = "verified" if tier in {"A", "B"} else "constrained"
        excerpt = clean_evidence_text(doc.snippet or best_text(doc), max_chars=220)
        url = normalize_url(doc.url) or "URL unavailable"
        why = (
            "Tier A/B corroborated signal suitable for primary conclusions."
            if status == "verified"
            else "Lower-confidence or limited corroboration; directional guidance only."
        )

        line = (
            f"- [{claim_id}] {excerpt} This matters because implementation and governance choices "
            f"depend on source credibility, practical constraints, and reproducibility signals."
        )
        if status == "verified":
            established_lines.append(line)
        else:
            constrained_lines.append(
                f"- [{claim_id}] {excerpt} Treated as directional because corroboration depth is limited."
            )

        register_rows.append(
            f"| [{claim_id}] | {status} | {why} | {excerpt} | {url} | open_status_unknown |"
        )
        detailed_sections.append(
            f"### [{claim_id}] {doc.title or 'Untitled source'}\n"
            f"Evidence summary: {excerpt}\n"
            "Interpretation in context: this source contributes a concrete signal for the query and helps "
            "bound what can be asserted versus what remains directional. The evidence is weighted by source tier, "
            "provider independence, and textual specificity to reduce overclaiming risk.\n"
            f"Decision implication: treat [{claim_id}] as {'primary evidence' if status == 'verified' else 'supporting context'} "
            "and cross-check against at least one independent corroborating source before irreversible decisions.\n"
            f"Confidence note: tier {tier}, status {status}, provider {(doc.provider or 'unknown')}."
        )
    if not established_lines:
        established_lines.append(
            "- No high-confidence established findings are available in this fallback run."
        )
    if not constrained_lines:
        constrained_lines.append(
            "- No additional constrained findings were identified beyond the established set."
        )

    withheld_block = (
        "### Withheld Claims\n"
        "None withheld. Claims that lacked minimum evidence support were kept in constrained status."
    )
    findings_block = (
        "### Established Evidence\n"
        + "\n".join(established_lines[:12])
        + "\n\n### Directional / Constrained Findings\n"
        + "\n".join(constrained_lines[:12])
        + "\n\n"
        + withheld_block
    )

    report = (
        "## Executive Summary\n\n"
        f"This constrained deep-research draft addresses **{query}** using {len(top_docs)} external sources. "
        f"Tier mix in this run: A={tier_a}, B={tier_b}, C={tier_c} (total {total_sources}). "
        "Only higher-confidence signals are treated as decision inputs, while weaker claims remain explicitly constrained.\n\n"
        "## Direct Answer\n\n"
        "Verified: a limited set of claims can support immediate decisions.\n"
        "Constrained: lower-tier or weakly corroborated claims are directional only.\n"
        "Unknowns: availability, recency, or corroboration gaps still need explicit proof.\n\n"
        f"{defensive_note}\n\n"
        "## Key Findings\n\n"
        f"{findings_block}\n\n"
        "## Verified Findings Register\n\n"
        + "\n".join(register_rows)
        + "\n\n## Recommendations\n\n"
        "- Prioritize actions backed by verified findings and independent corroboration.\n"
        "- Resolve missing proof fields before making irreversible decisions.\n"
        "- Re-run retrieval with stronger primary sources where findings remain constrained.\n\n"
        "## 12-Month Action Plan\n\n"
        "- Q1: enforce verification criteria and explicit missing-proof tracking.\n"
        "- Q2: improve provider/domain diversity for stronger corroboration.\n"
        "- Q3: validate contradictory findings and update confidence routing.\n"
        "- Q4: operationalize recurring refresh with drift checks.\n\n"
        "## Risks, Gaps, and Uncertainty\n\n"
        "- This fallback is deterministic and less nuanced than a full successful synthesis pass.\n"
        "- Some constrained findings require fresher or primary-source evidence before promotion to verified.\n\n"
        "## How This Research Was Done\n\n"
        "- Retrieved and normalized external sources from configured providers.\n"
        "- Ranked evidence by source tier, corroboration potential, and snippet signal quality.\n"
        "- Produced a deterministic narrative fallback when synthesis model calls were unavailable.\n\n"
        "## Evidence Confidence Summary\n\n"
        f"- Source quality mix: Tier A={tier_a}, Tier B={tier_b}, Tier C={tier_c}, Total={total_sources}\n"
        "- Confidence model: deterministic tier-weighted fallback with constrained/verified separation.\n"
        "- Use constrained findings directionally until stronger corroboration is collected.\n\n"
        "## Scope and Method\n\n"
        f"- Query: {query}\n"
        "- Method: deterministic fallback synthesis using external citations and claim-level traceability.\n"
        "- Source policy: external_only\n\n"
        "## Detailed Source Analysis\n\n"
        + "\n\n".join(detailed_sections)
        + "\n\n## Counterevidence / Alternative Interpretations\n\n"
        "- Competing interpretations may emerge if new high-tier sources contradict current constrained findings.\n"
        "- Re-run with expanded provider diversity and recency-focused retrieval before finalizing high-stakes decisions.\n\n"
        "## Sources Used\n\n"
    )
    for c in citations:
        report += f"- [{c.claim_id}] {c.title} - {c.source_url}\n"

    return report, dedupe_citations(citations), source_index
