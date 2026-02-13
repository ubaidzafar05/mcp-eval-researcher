from __future__ import annotations

import re
from collections.abc import Iterable

from core.models import Citation

CLAIM_PATTERN = re.compile(r"\[(C\d+)\]")


def extract_claim_ids(report: str) -> list[str]:
    return sorted(set(CLAIM_PATTERN.findall(report or "")))


def citation_index(citations: Iterable[Citation]) -> dict[str, list[Citation]]:
    table: dict[str, list[Citation]] = {}
    for citation in citations:
        table.setdefault(citation.claim_id, []).append(citation)
    return table


def citation_coverage(report: str, citations: list[Citation]) -> float:
    claims = extract_claim_ids(report)
    if not claims:
        return 0.0
    lookup = citation_index(citations)
    cited = sum(1 for claim in claims if lookup.get(claim))
    return cited / len(claims)


def validate_claim_level_citations(
    report: str,
    citations: list[Citation],
    *,
    min_coverage: float = 0.85,
) -> tuple[bool, list[str], float]:
    claims = extract_claim_ids(report)
    if not claims:
        return False, ["No claim IDs (for example [C1]) were found in report."], 0.0

    lookup = citation_index(citations)
    missing = [claim for claim in claims if claim not in lookup]
    coverage = citation_coverage(report, citations)
    reasons: list[str] = []
    if missing:
        reasons.append(f"Missing citations for claims: {', '.join(missing)}")
    if coverage < min_coverage:
        reasons.append(
            f"Citation coverage {coverage:.2f} is below threshold {min_coverage:.2f}"
        )
    return not reasons, reasons, coverage

