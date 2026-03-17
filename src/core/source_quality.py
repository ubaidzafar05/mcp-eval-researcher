from __future__ import annotations

import re
from urllib.parse import urlparse

from core.models import QueryProfile, RetrievedDoc

TIER_A_DOMAINS = {
    "arxiv.org",
    "nature.com",
    "science.org",
    "aclanthology.org",
    "openreview.net",
    "semanticscholar.org",
    "ieee.org",
    "acm.org",
    "nasa.gov",
    "nist.gov",
    "who.int",
    "oecd.org",
    "europa.eu",
    "aaai.org",
}

TIER_B_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "mckinsey.com",
    "gartner.com",
    "forrester.com",
    "mit.edu",
    "stanford.edu",
    "openai.com",
    "anthropic.com",
    "brookings.edu",
    "chicagobooth.edu",
}

LOW_TRUST_DOMAINS = {
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "substack.com",
    "medium.com",
    "quora.com",
    "reddit.com",
}

BOILERPLATE_PATTERNS = (
    "copyright",
    "all rights reserved",
    "privacy policy",
    "terms of use",
    "cookie policy",
    "share on",
    "subscribe",
    "menu",
    "navigation",
    "sign in",
    "log in",
    "join the team",
    "product",
    "resources",
    "company",
    "legal",
)

PRIMARY_PAGE_HINTS = (
    "admission",
    "apply",
    "application",
    "program",
    "scholarship",
    "fellowship",
    "funding",
    "deadline",
    "eligibility",
    "intake",
)

OPEN_STATUS_HINTS = (
    "applications open",
    "application open",
    "open now",
    "accepting applications",
    "active intake",
    "apply now",
    "deadline",
    "intake",
)


def _hostname(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_known_domain(host: str, candidates: set[str]) -> bool:
    return host in candidates or any(host.endswith(f".{domain}") for domain in candidates)


def _is_primary_edu_page(url: str, title: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not host.endswith(".edu"):
        return False
    blob = f"{(parsed.path or '').lower()} {(title or '').lower()}"
    return any(hint in blob for hint in PRIMARY_PAGE_HINTS)


def source_tier(url: str, provider: str = "", title: str = "") -> str:
    host = _hostname(url)
    if not host:
        return "unknown"
    if host.endswith(".gov"):
        return "A"
    if _is_primary_edu_page(url, title):
        return "A"
    if host.endswith(".edu"):
        return "B"
    if _is_known_domain(host, TIER_A_DOMAINS):
        return "A"
    if _is_known_domain(host, TIER_B_DOMAINS):
        return "B"
    if _is_known_domain(host, LOW_TRUST_DOMAINS):
        return "C"
    if provider in {"tavily", "ddg", "firecrawl"} and title:
        return "C"
    return "unknown"


def evidence_confidence(tier: str, snippet: str) -> str:
    text_len = len((snippet or "").strip())
    if tier == "A":
        return "high" if text_len >= 120 else "medium"
    if tier == "B":
        return "medium" if text_len >= 120 else "low"
    if tier == "C":
        return "low"
    return "unknown"


def is_boilerplate_line(line: str) -> bool:
    value = (line or "").strip().lower()
    if not value:
        return True
    return any(marker in value for marker in BOILERPLATE_PATTERNS)


def clean_evidence_text(text: str, *, max_chars: int = 180) -> str:
    source = (text or "").replace("\\n", "\n")
    source = re.sub(r"<[^>]+>", " ", source)
    source = re.sub(r"(^|\s)(menu|home|about|contact|privacy|terms)\s*(\||/|$)", " ", source, flags=re.IGNORECASE)
    lines = [ln.strip() for ln in source.splitlines()]
    cleaned = [ln for ln in lines if ln and not is_boilerplate_line(ln)]
    if not cleaned:
        cleaned = [re.sub(r"\s+", " ", source).strip()]
    normalized = re.sub(r"\s+", " ", " ".join(cleaned)).strip()
    return normalized[: max(40, max_chars)].strip()


def is_low_trust_source(url: str, title: str = "") -> bool:
    host = _hostname(url)
    if _is_known_domain(host, LOW_TRUST_DOMAINS):
        return True
    lowered_title = (title or "").lower()
    low_signal_words = ("sponsored", "affiliate", "promoted", "viral", "reel", "shorts")
    return any(word in lowered_title for word in low_signal_words)


def annotate_doc(doc: RetrievedDoc, *, max_evidence_chars: int = 180) -> RetrievedDoc:
    tier = source_tier(doc.url, doc.provider, doc.title)
    evidence = clean_evidence_text(doc.snippet or doc.content, max_chars=max_evidence_chars)
    confidence = evidence_confidence(tier, evidence)
    meta = dict(doc.meta or {})
    meta["source_tier"] = tier
    meta["confidence"] = confidence
    meta["publisher"] = _hostname(doc.url) or "unknown"
    return doc.model_copy(
        update={
            "snippet": evidence,
            "meta": meta,
        }
    )


def tier_rank(tier: str) -> int:
    if tier == "A":
        return 3
    if tier == "B":
        return 2
    if tier == "C":
        return 1
    return 0


def prioritize_docs(
    docs: list[RetrievedDoc],
    *,
    source_quality_bar: str,
    min_tier_ab_sources: int,
) -> list[RetrievedDoc]:
    annotated = [annotate_doc(doc) for doc in docs]
    ranked = sorted(
        annotated,
        key=lambda d: (
            1 if is_low_trust_source(d.url, d.title) else 0,
            -tier_rank(str((d.meta or {}).get("source_tier", "unknown"))),
            -float(d.score or 0.0),
            d.title.lower(),
        ),
    )
    if source_quality_bar == "broad":
        return ranked
    ab_docs = [
        doc
        for doc in ranked
        if str((doc.meta or {}).get("source_tier", "unknown")) in {"A", "B"}
    ]
    c_docs = [
        doc
        for doc in ranked
        if str((doc.meta or {}).get("source_tier", "unknown")) == "C"
    ]
    if source_quality_bar == "high_confidence":
        if len(ab_docs) >= min_tier_ab_sources:
            prioritized_c = [doc for doc in c_docs if not is_low_trust_source(doc.url, doc.title)]
            deprioritized_c = [doc for doc in c_docs if is_low_trust_source(doc.url, doc.title)]
            return ab_docs + prioritized_c + deprioritized_c
        return ranked
    # mixed
    return ab_docs + c_docs if ab_docs else ranked


def quality_stats(citations: list[dict | object]) -> dict[str, int]:
    tier_counts = {"A": 0, "B": 0, "C": 0, "unknown": 0}
    for citation in citations:
        tier = "unknown"
        if isinstance(citation, dict):
            tier = str(citation.get("source_tier") or "unknown")
        elif hasattr(citation, "source_tier"):
            tier = str(citation.source_tier or "unknown")  # type: ignore[attr-defined]
        tier_counts[tier if tier in tier_counts else "unknown"] += 1
    tier_counts["tier_ab"] = tier_counts["A"] + tier_counts["B"]
    return tier_counts


def _constraint_tokens(value: str, *, min_len: int = 3) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{1,}", (value or "").lower())
    return [token for token in tokens if len(token) >= min_len]


def _core_query_terms(profile: QueryProfile) -> list[str]:
    terms: list[str] = []
    terms.extend(_constraint_tokens(profile.normalized_query))
    for facet in profile.domain_facets:
        terms.extend(_constraint_tokens(facet))
    for value in (profile.typed_constraints or {}).values():
        terms.extend(_constraint_tokens(value))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _doc_blob(doc: RetrievedDoc) -> str:
    return " ".join(
        (
            (doc.title or "").lower(),
            (doc.snippet or "").lower(),
            (doc.content or "")[:1800].lower(),
            (doc.url or "").lower(),
        )
    )


def doc_matches_query_intent(
    doc: RetrievedDoc,
    profile: QueryProfile,
    *,
    min_term_hits: int = 2,
) -> bool:
    blob = _doc_blob(doc)
    terms = _core_query_terms(profile)
    if not terms:
        return True
    hit_count = sum(1 for term in terms if term in blob)
    if hit_count < min_term_hits:
        return False

    constraints = profile.typed_constraints or {}
    availability_required = constraints.get("availability_constraint") == "must_be_open"
    if availability_required and not any(marker in blob for marker in OPEN_STATUS_HINTS):
        return False

    location_value = constraints.get("location_constraint", "")
    if location_value:
        location_tokens = _constraint_tokens(location_value, min_len=4)
        if location_tokens and not any(token in blob for token in location_tokens):
            return False

    eligibility_value = constraints.get("eligibility_constraint", "")
    if eligibility_value:
        eligibility_tokens = _constraint_tokens(eligibility_value, min_len=5)
        if eligibility_tokens:
            overlap = sum(1 for token in eligibility_tokens if token in blob)
            if overlap == 0:
                return False

    return True


def filter_docs_for_query(
    docs: list[RetrievedDoc],
    profile: QueryProfile,
    *,
    min_term_hits: int = 2,
) -> tuple[list[RetrievedDoc], dict[str, int]]:
    kept: list[RetrievedDoc] = []
    off_topic_count = 0
    for doc in docs:
        if doc_matches_query_intent(doc, profile, min_term_hits=min_term_hits):
            kept.append(doc)
        else:
            off_topic_count += 1
    return kept, {"off_topic_count": off_topic_count}
