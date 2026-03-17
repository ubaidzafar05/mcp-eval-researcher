from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

from core.models import Citation

CLAIM_PATTERN = re.compile(r"\[(C\d+)\]")
EXTERNAL_PROVIDERS = {"tavily", "ddg", "firecrawl"}


def extract_claim_ids(report: str) -> list[str]:
    return sorted(set(CLAIM_PATTERN.findall(report or "")))


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query="",
        fragment="",
    )
    value = urlunparse(normalized).rstrip("/")
    return value


def normalized_domain(url: str) -> str:
    normalized = normalize_url(url)
    if not normalized:
        return ""
    host = (urlparse(normalized).netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_external_provider(provider: str) -> bool:
    return (provider or "").strip().lower() in EXTERNAL_PROVIDERS


def is_external_citation(citation: Citation) -> bool:
    return is_external_provider(citation.provider) and bool(normalize_url(citation.source_url))


def dedupe_citations(citations: Iterable[Citation]) -> list[Citation]:
    seen: set[tuple[str, str, str]] = set()
    result: list[Citation] = []
    for citation in citations:
        key = (
            citation.claim_id.strip(),
            normalize_url(citation.source_url),
            citation.provider.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(
            citation.model_copy(
                update={
                    "source_url": normalize_url(citation.source_url),
                    "source_tier": citation.source_tier or "unknown",
                    "confidence": citation.confidence or "unknown",
                }
            )
        )
    return result


def filter_citations_by_policy(
    citations: list[Citation],
    *,
    source_policy: str = "external_only",
) -> list[Citation]:
    cleaned = dedupe_citations(citations)
    if source_policy == "mixed":
        return cleaned
    if source_policy == "external_preferred":
        external = [c for c in cleaned if is_external_citation(c)]
        return external if external else cleaned
    return [c for c in cleaned if is_external_citation(c)]


def citation_index(citations: Iterable[Citation]) -> dict[str, list[Citation]]:
    table: dict[str, list[Citation]] = {}
    for citation in citations:
        table.setdefault(citation.claim_id, []).append(citation)
    return table


def citation_coverage(report: str, citations: list[Citation]) -> float:
    claims = extract_claim_ids(report)
    if not claims:
        return 0.0
    lookup = citation_index(dedupe_citations(citations))
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

    cleaned_citations = dedupe_citations(citations)
    lookup = citation_index(cleaned_citations)
    missing = [claim for claim in claims if claim not in lookup]
    coverage = citation_coverage(report, cleaned_citations)
    reasons: list[str] = []
    if missing:
        reasons.append(f"Missing citations for claims: {', '.join(missing)}")
    if coverage < min_coverage:
        reasons.append(
            f"Citation coverage {coverage:.2f} is below threshold {min_coverage:.2f}"
        )
    return not reasons, reasons, coverage


def source_integrity_stats(citations: list[Citation]) -> dict[str, int]:
    cleaned = dedupe_citations(citations)
    external = [c for c in cleaned if is_external_citation(c)]
    tier_a = sum(1 for c in external if (c.source_tier or "").upper() == "A")
    tier_b = sum(1 for c in external if (c.source_tier or "").upper() == "B")
    tier_c = sum(1 for c in external if (c.source_tier or "").upper() == "C")
    return {
        "total_citations": len(cleaned),
        "external_citations": len(external),
        "unique_external_urls": len(
            {normalize_url(c.source_url) for c in external if normalize_url(c.source_url)}
        ),
        "unique_external_domains": len(
            {normalized_domain(c.source_url) for c in external if normalized_domain(c.source_url)}
        ),
        "unique_external_providers": len(
            {c.provider.strip().lower() for c in external if c.provider.strip()}
        ),
        "tier_a_sources": tier_a,
        "tier_b_sources": tier_b,
        "tier_c_sources": tier_c,
        "tier_ab_sources": tier_a + tier_b,
    }


def validate_source_integrity(
    citations: list[Citation],
    *,
    source_policy: str,
    min_external_sources: int,
    min_unique_domains: int = 0,
    min_unique_providers: int,
    allow_relaxed_diversity: bool = False,
    min_tier_ab_sources: int = 0,
    max_ctier_claim_ratio: float = 1.0,
    require_corroboration_for_tier_c: bool = False,
) -> tuple[bool, list[str], dict[str, int]]:
    cleaned = dedupe_citations(citations)
    reasons: list[str] = []
    stats = source_integrity_stats(cleaned)
    has_non_external = any(not is_external_citation(c) for c in cleaned)

    if source_policy == "external_only" and has_non_external:
        reasons.append(
            "Source policy is external_only, but one or more citations are missing valid external URLs."
        )
    if stats["unique_external_urls"] < min_external_sources:
        reasons.append(
            f"Only {stats['unique_external_urls']} unique external sources were found; "
            f"minimum required is {min_external_sources}."
        )
    if min_unique_domains > 0 and stats["unique_external_domains"] < min_unique_domains:
        reasons.append(
            f"Only {stats['unique_external_domains']} unique external domains were found; "
            f"minimum required is {min_unique_domains}."
        )
    provider_min = min_unique_providers
    # Only relax provider diversity when explicitly running under quota pressure mode.
    if allow_relaxed_diversity and stats["unique_external_urls"] >= max(8, min_external_sources + 3):
        provider_min = min(provider_min, 1)

    if stats["unique_external_providers"] < provider_min:
        reasons.append(
            f"Only {stats['unique_external_providers']} external providers were found; "
            f"minimum required is {provider_min}."
        )
    if min_tier_ab_sources > 0 and stats["tier_ab_sources"] < min_tier_ab_sources:
        reasons.append(
            f"Only {stats['tier_ab_sources']} Tier A/B sources were found; "
            f"minimum required is {min_tier_ab_sources}."
        )
    if stats["external_citations"] > 0 and 0.0 <= max_ctier_claim_ratio < 1.0:
        c_ratio = stats["tier_c_sources"] / max(1, stats["external_citations"])
        if c_ratio > max_ctier_claim_ratio:
            reasons.append(
                f"Tier C claim ratio {c_ratio:.2f} exceeds maximum allowed {max_ctier_claim_ratio:.2f}."
            )
    if require_corroboration_for_tier_c and stats["tier_c_sources"] > 0:
        if stats["tier_ab_sources"] <= 0:
            reasons.append(
                "Tier C claims require at least one corroborating Tier A/B source in the report."
            )
    return not reasons, reasons, stats
