from __future__ import annotations

import re
from typing import Literal

from core.citations import extract_claim_ids

HEADING_PATTERN = re.compile(r"^##\s+(.+)$", flags=re.MULTILINE)
WORD_PATTERN = re.compile(r"\b[\w'-]+\b")
URL_PATTERN = re.compile(r"https?://\S+")

REQUIRED_HEADINGS = (
    "executive summary",
    "direct answer",
    "key findings",
    "verified findings register",
    "recommendations",
    "12-month action plan",
    "risks, gaps, and uncertainty",
    "sources used",
)

ACADEMIC_REQUIRED_HEADINGS = (
    "abstract",
    "introduction",
    "theoretical framework",
    "literature review",
    "hypotheses",
    "methodology",
    "metrics & evaluation",
    "formal modeling of prompting",
    "empirical results",
    "generalization & scaling laws",
    "theoretical contributions",
    "practical contributions",
    "limitations",
    "ethical & governance considerations",
    "future research directions",
    "conclusion",
    "appendices",
    "sources used",
)

# Legacy headings â€” accepted as valid but not required.
ACCEPTED_HEADINGS = REQUIRED_HEADINGS + (
    "evidence confidence summary",
    "scope and method",
    "evidence matrix",
    "how this research was done",
    "counterevidence and alternative interpretations",
    "detailed source analysis",
    "counterevidence / alternative interpretations",
    "evidence agreement and disagreement",
    "scenario outlook",
)


def _required_headings_for_mode(report_structure_mode: str) -> tuple[str, ...]:
    if report_structure_mode == "academic_17":
        return ACADEMIC_REQUIRED_HEADINGS
    return REQUIRED_HEADINGS

PLACEHOLDER_MARKERS = (
    "key findings require further structuring",
    "this report summarizes evidence collected from available sources",
    "pending stronger corroboration",
    "refer to claim-level citations in the report",
)


def _norm(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _split_sources_section(report: str) -> tuple[str, str]:
    marker = re.search(r"(?im)^##\s+sources used\s*$", report)
    if not marker:
        return report.rstrip(), ""
    return report[: marker.start()].rstrip(), report[marker.end() :].strip()


def collect_missing_required_sections(
    report: str,
    *,
    report_structure_mode: str = "decision_brief",
) -> list[str]:
    body = (report or "").strip()
    required_headings = _required_headings_for_mode(report_structure_mode)
    if not body:
        return list(required_headings)
    headings = {_norm(h) for h in HEADING_PATTERN.findall(body)}
    return [h for h in required_headings if h not in headings]


def detect_placeholder_content(report: str) -> list[str]:
    lowered = (report or "").lower()
    hits = [marker for marker in PLACEHOLDER_MARKERS if marker in lowered]
    if re.search(r"https://example\.com(?:\s|\||$)", lowered):
        hits.append("example_com_placeholder_domain")
    if re.search(
        r"\|\s*\[c1\]\s*\|\s*constrained\s*\|\s*missing verification floor\s*\|\s*pending stronger corroboration\s*\|\s*https://example\.com\s*\|",
        lowered,
    ):
        hits.append("verified_register_placeholder_row")
    return list(dict.fromkeys(hits))


def ensure_required_sections(report: str, *, allow_placeholder_sections: bool = False) -> str:
    body = (report or "").strip()
    if not body:
        return report

    if not allow_placeholder_sections:
        return body

    body_no_sources, existing_sources = _split_sources_section(body)
    headings = {_norm(h) for h in HEADING_PATTERN.findall(body_no_sources)}
    additions: list[str] = []
    for heading in REQUIRED_HEADINGS:
        if heading in headings:
            continue
        heading_title = heading.title().replace("And", "and")
        additions.append(
            f"## {heading_title}\n"
            "- Section placeholder added by template_fill mode. Replace with verified content before publishing."
        )
    merged = body_no_sources
    if additions:
        merged = f"{merged}\n\n" + "\n\n".join(additions)
    if "sources used" not in headings:
        sources_block = existing_sources or "- No source ledger was provided in this draft."
        merged = f"{merged}\n\n## Sources Used\n{sources_block.strip()}"
    return merged.strip()


def _extract_sources_section(body: str) -> str:
    marker = re.search(r"(?im)^##\s+sources used\s*$", body)
    if not marker:
        return ""
    return body[marker.end():].strip()


def assess_report_quality(
    report: str,
    *,
    query: str = "",
    depth: Literal["fast", "balanced", "deep"] = "deep",
    min_words: int | None = None,
    min_claims: int | None = None,
    min_required_sections: int | None = None,
    require_source_urls: bool = True,
    report_structure_mode: str = "decision_brief",
    insight_density_min: int | None = None,
    mechanics_ratio_max_top_sections: float | None = None,
    top_section_min_verified_claims: int = 3,
    top_section_max_ctier_ratio: float = 0.20,
) -> tuple[bool, list[str], dict[str, int | float]]:
    body = (report or "").strip()
    required_headings = _required_headings_for_mode(report_structure_mode)
    if not body:
        return False, ["Report is empty."], {
            "word_count": 0,
            "claim_count": 0,
            "required_sections_present": 0,
            "required_sections_total": len(required_headings),
            "section_coverage": 0.0,
        }

    if min_words is None:
        min_words = 1500 if depth == "deep" else 400 if depth == "balanced" else 150
    if min_claims is None:
        min_claims = 6 if depth == "deep" else 3 if depth == "balanced" else 2
    if min_required_sections is None:
        min_required_sections = (
            14 if report_structure_mode == "academic_17" and depth == "deep"
            else 12 if report_structure_mode == "academic_17" and depth == "balanced"
            else 10 if report_structure_mode == "academic_17"
            else 5 if depth == "deep"
            else 4 if depth == "balanced"
            else 3
        )
    if insight_density_min is None:
        insight_density_min = 8 if report_structure_mode == "academic_17" else (10 if depth == "deep" else 4 if depth == "balanced" else 2)
    if mechanics_ratio_max_top_sections is None:
        mechanics_ratio_max_top_sections = 0.018 if report_structure_mode == "academic_17" else 0.025

    words = WORD_PATTERN.findall(body)
    word_count = len(words)
    claim_ids = extract_claim_ids(body)
    claim_count = len(claim_ids)

    headings = {_norm(h) for h in HEADING_PATTERN.findall(body)}
    required_present = [h for h in required_headings if h in headings]
    missing_required = [h for h in required_headings if h not in headings]

    required_count = len(required_present)
    section_coverage = required_count / len(required_headings)
    source_url_count = len(URL_PATTERN.findall(_extract_sources_section(body)))
    query_tokens = {w for w in WORD_PATTERN.findall((query or "").lower()) if len(w) > 3}
    report_tokens = {w for w in WORD_PATTERN.findall(body.lower()) if len(w) > 3}
    alignment_score = (
        len(query_tokens & report_tokens) / max(1, len(query_tokens))
        if query_tokens
        else 1.0
    )
    boilerplate_markers = (
        "privacy policy",
        "terms of use",
        "all rights reserved",
        "copyright",
        "share on",
        "log in",
        "sign in",
        "cookie policy",
    )
    lower_body = body.lower()
    boilerplate_hits = sum(lower_body.count(marker) for marker in boilerplate_markers)
    boilerplate_ratio = boilerplate_hits / max(1, word_count)
    trigrams: dict[str, int] = {}
    tokens = WORD_PATTERN.findall(lower_body)
    for idx in range(max(0, len(tokens) - 2)):
        tri = " ".join(tokens[idx:idx + 3])
        trigrams[tri] = trigrams.get(tri, 0) + 1
    repeated_trigrams = sum(v for v in trigrams.values() if v >= 3)
    repetition_ratio = repeated_trigrams / max(1, len(tokens))
    analytical_markers = ("because", "therefore", "however", "indicates", "suggests", "implies")
    analytical_statements = sum(1 for line in body.splitlines() if any(m in line.lower() for m in analytical_markers))
    mechanics_markers = (
        "evidence matrix",
        "sources used",
        "claim-level",
        "tier",
        "provider",
        "confidence",
        "source policy",
    )
    body_without_headings = re.sub(r"(?m)^##\s+.+$", "", lower_body)
    mechanics_hits = sum(body_without_headings.count(marker) for marker in mechanics_markers)
    mechanics_ratio = mechanics_hits / max(1, word_count)
    exec_match = re.search(
        r"(?ims)^##\s+Executive Summary\s*(.+?)(?=^##\s+|\Z)",
        body,
    )
    executive_body = exec_match.group(1).strip() if exec_match else ""
    executive_words = len(WORD_PATTERN.findall(executive_body))
    executive_claim_density = len(re.findall(r"\[C\d+\]", executive_body)) / max(1, executive_words)
    direct_match = re.search(
        r"(?ims)^##\s+Direct Answer\s*(.+?)(?=^##\s+|\Z)",
        body,
    )
    direct_answer_body = direct_match.group(1).strip() if direct_match else ""
    direct_answer_words = len(WORD_PATTERN.findall(direct_answer_body))
    direct_answer_signals = ("in short", "the answer", "overall", "in practice", "this means")
    direct_answer_present = any(signal in direct_answer_body.lower() for signal in direct_answer_signals) or direct_answer_words >= 45

    analytical_density = analytical_statements / max(1, len(body.splitlines()))
    if analytical_density > 0.12:
        min_words = int(min_words * 0.7)

    reasons: list[str] = []
    if word_count < min_words:
        reasons.append(
            f"Report is too brief ({word_count} words). Minimum expected is {min_words}."
        )
    if required_count < min_required_sections:
        reasons.append(
            "Report structure is weak. Include more required sections: "
            + ", ".join(missing_required[:3])
            + ("..." if len(missing_required) > 3 else "")
        )
    if claim_count < min_claims:
        reasons.append(
            f"Report has too few cited claims ({claim_count}). Minimum expected is {min_claims}."
        )

    if report_structure_mode == "academic_17":
        for required in ("abstract", "methodology", "empirical results", "conclusion", "appendices"):
            if required not in headings:
                reasons.append(f"Missing required academic section: {required}.")
    else:
        if "direct answer" not in headings:
            reasons.append("Missing direct answer section.")
        if "verified findings register" not in headings:
            reasons.append("Missing verified findings register section.")
        if "12-month action plan" not in headings:
            reasons.append("Missing action plan section.")
        if "risks, gaps, and uncertainty" not in headings:
            reasons.append("Missing explicit uncertainty section.")
        if "recommendations" not in headings:
            reasons.append("Missing recommendations section.")

    if require_source_urls and source_url_count <= 0:
        reasons.append("Sources section does not contain valid URLs.")
    placeholder_hits = detect_placeholder_content(body)
    if placeholder_hits:
        reasons.append(
            "Placeholder content detected in report body: " + ", ".join(placeholder_hits[:3])
        )
    if alignment_score < 0.2:
        reasons.append(
            f"Query-answer alignment is weak ({alignment_score:.2f}). The report appears off-topic."
        )
    if boilerplate_ratio > 0.015:
        reasons.append(
            f"Boilerplate/noise ratio is high ({boilerplate_ratio:.3f}); clean extracted evidence text."
        )
    if repetition_ratio > 0.07:
        reasons.append(
            f"Repeated phrase density is high ({repetition_ratio:.3f}); reduce templated repetition."
        )
    if mechanics_ratio > mechanics_ratio_max_top_sections:
        reasons.append(
            "Report is citation-inventory heavy and answer-light; increase analytical narrative density."
        )

    min_exec_words = 60 if depth == "deep" else 30 if depth == "balanced" else 15
    if report_structure_mode != "academic_17":
        if executive_words < min_exec_words or executive_claim_density > 0.08:
            reasons.append(
                "Top narrative does not explain query in domain language with clear depth."
            )
        if not direct_answer_present:
            reasons.append(
                "Top narrative does not explain query in domain language with a clear direct answer."
            )
        if (
            "verified" not in direct_answer_body.lower()
            or "constrained" not in direct_answer_body.lower()
            or ("unknown" not in direct_answer_body.lower() and "uncertain" not in direct_answer_body.lower())
        ):
            reasons.append(
                "Direct answer must explicitly separate verified, constrained, and unknown elements."
            )

    min_analytical = insight_density_min
    if analytical_statements < min_analytical:
        reasons.append(
            f"Too few analytical statements ({analytical_statements}); minimum expected is {min_analytical}."
        )

    register_rows = re.findall(
        r"(?im)^\|\s*\[C\d+\]\s*\|\s*(verified|constrained|withheld)\s*\|",
        body,
    )
    total_register = len(register_rows)
    constrained_or_withheld = sum(1 for status in register_rows if status.lower() in {"constrained", "withheld"})
    ctier_proxy_ratio = constrained_or_withheld / max(1, total_register)
    if (
        report_structure_mode == "academic_17"
        and total_register > 0
        and ctier_proxy_ratio > top_section_max_ctier_ratio
    ):
        reasons.append(
            "Top sections rely too heavily on constrained/withheld findings; improve verified evidence ratio."
        )

    if report_structure_mode == "academic_17":
        top_claim_refs = 0
        for section in ("abstract", "introduction", "empirical results", "conclusion"):
            match = re.search(rf"(?ims)^##\s+{re.escape(section)}\s*(.+?)(?=^##\s+|\Z)", body)
            if match:
                top_claim_refs += len(re.findall(r"\[C\d+\]", match.group(1)))
        if top_claim_refs < max(1, top_section_min_verified_claims):
            reasons.append(
                f"Top academic sections have too few claim-grounded references ({top_claim_refs}); minimum expected is {top_section_min_verified_claims}."
            )

    if "unknown" not in lower_body and "uncertain" not in lower_body and "insufficient evidence" not in lower_body:
        reasons.append("Report should explicitly state unknowns or uncertainty boundaries.")

    metrics: dict[str, int | float] = {
        "word_count": word_count,
        "claim_count": claim_count,
        "source_url_count": source_url_count,
        "query_alignment_score": round(alignment_score, 3),
        "boilerplate_ratio": round(boilerplate_ratio, 4),
        "repetition_ratio": round(repetition_ratio, 4),
        "analytical_statements": analytical_statements,
        "source_mechanics_ratio": round(mechanics_ratio, 4),
        "executive_words": executive_words,
        "direct_answer_words": direct_answer_words,
        "placeholder_hits": len(placeholder_hits),
        "required_sections_present": required_count,
        "required_sections_total": len(required_headings),
        "section_coverage": round(section_coverage, 3),
        "ctier_proxy_ratio": round(ctier_proxy_ratio, 4),
    }
    return not reasons, reasons, metrics
