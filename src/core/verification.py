from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from core.citations import normalize_url, normalized_domain
from core.models import QueryProfile, RetrievedDoc
from core.query_profile import is_opportunity_query
from core.source_quality import clean_evidence_text, source_tier

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]{2,}")
ISO_DATE_PATTERN = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
MONTH_DATE_PATTERN = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2}),?\s+(20\d{2})\b",
    flags=re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

OPEN_MARKERS = (
    "applications open",
    "apply now",
    "accepting applications",
    "open for applications",
    "currently available",
    "active intake",
    "admissions open",
)

CLOSED_MARKERS = (
    "applications closed",
    "not accepting applications",
    "deadline passed",
    "closed for admissions",
    "intake closed",
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

UNKNOWN_DATE = object()


@dataclass
class RetrievalFilterStats:
    candidate_count: int = 0
    filtered_count: int = 0
    kept_count: int = 0
    stale_count: int = 0
    off_topic_count: int = 0
    low_signal_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "candidate_count": self.candidate_count,
            "filtered_count": self.filtered_count,
            "kept_count": self.kept_count,
            "stale_count": self.stale_count,
            "off_topic_count": self.off_topic_count,
            "low_signal_count": self.low_signal_count,
        }


@dataclass
class ClaimVerificationResult:
    claim_id: str
    status: str
    reason_codes: list[str]
    corroboration_count: int
    primary_or_official: bool
    freshness_ok: bool | None
    open_status: str
    relevance_score: float


def _doc_text(doc: RetrievedDoc) -> str:
    return clean_evidence_text(
        f"{doc.title} {doc.snippet} {doc.content}",
        max_chars=460,
    ).lower()


def _tokenize(value: str) -> set[str]:
    return {tok.lower() for tok in TOKEN_PATTERN.findall(value or "")}


def _query_tokens(query: str, facets: list[str]) -> set[str]:
    text = f"{query} {' '.join(facets)}"
    return {tok for tok in _tokenize(text) if len(tok) >= 4}


def relevance_score(doc: RetrievedDoc, *, query: str, facets: list[str]) -> float:
    q_tokens = _query_tokens(query, facets)
    if not q_tokens:
        return 0.5
    d_tokens = _tokenize(_doc_text(doc))
    overlap = len(q_tokens & d_tokens)
    return min(1.0, overlap / max(3, min(12, len(q_tokens))))


def detect_open_status(text: str) -> str:
    lowered = (text or "").lower()
    if any(marker in lowered for marker in CLOSED_MARKERS):
        return "closed"
    if any(marker in lowered for marker in OPEN_MARKERS):
        return "open"
    return "unknown"


def _month_number(name: str) -> int:
    order = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    return order.get(name[:3].lower(), 1)


def extract_document_date(doc: RetrievedDoc) -> datetime | None | object:
    meta = dict(doc.meta or {})
    raw_candidates = [
        str(meta.get("published_at") or ""),
        str(meta.get("updated_at") or ""),
        str(meta.get("date") or ""),
        f"{doc.title} {doc.snippet}",
    ]
    for raw in raw_candidates:
        if not raw:
            continue
        iso = ISO_DATE_PATTERN.search(raw)
        if iso:
            year, month, day = (int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            try:
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                pass
        month_match = MONTH_DATE_PATTERN.search(raw)
        if month_match:
            month = _month_number(month_match.group(1))
            day = int(month_match.group(2))
            year = int(month_match.group(3))
            try:
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                pass
        year_match = YEAR_PATTERN.search(raw)
        if year_match:
            year = int(year_match.group(1))
            return datetime(year, 1, 1, tzinfo=UTC)
    return UNKNOWN_DATE


def freshness_ok(doc: RetrievedDoc, *, max_months: int) -> tuple[bool | None, datetime | None]:
    doc_date = extract_document_date(doc)
    if doc_date is UNKNOWN_DATE:
        return None, None
    if doc_date is None:
        return None, None
    cutoff = datetime.now(tz=UTC) - timedelta(days=max(1, max_months) * 30)
    return doc_date >= cutoff, doc_date


def is_primary_or_official(doc: RetrievedDoc) -> bool:
    url = normalize_url(doc.url)
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    tier = source_tier(doc.url, doc.provider, doc.title).upper()
    page_blob = f"{path} {(doc.title or '').lower()} {(doc.snippet or '').lower()}"
    has_primary_page_hints = any(hint in page_blob for hint in PRIMARY_PAGE_HINTS)
    return (
        host.endswith(".gov")
        or (host.endswith(".edu") and has_primary_page_hints)
        or tier == "A"
        or "official" in (doc.title or "").lower()
    )


def has_deadline_or_cycle_date(doc: RetrievedDoc) -> bool:
    text = f"{doc.title} {doc.snippet} {doc.content}"
    if ISO_DATE_PATTERN.search(text):
        return True
    if MONTH_DATE_PATTERN.search(text):
        return True
    year_match = YEAR_PATTERN.search(text)
    if year_match:
        year = int(year_match.group(1))
        current_year = datetime.now(tz=UTC).year
        return current_year - 1 <= year <= current_year + 2
    return False


def _constraint_match(text: str, constraint: str) -> bool:
    tokens = [tok for tok in _tokenize(constraint) if len(tok) >= 4]
    if not tokens:
        return True
    text_tokens = _tokenize(text)
    overlap = len(set(tokens) & set(text_tokens))
    return overlap >= max(1, min(2, len(tokens)))


def query_requires_open_availability(
    profile: QueryProfile,
    *,
    availability_policy: str,
    availability_enforcement_scope: str = "intent_triggered",
    opportunity_query_detection: str = "auto",
    query: str = "",
) -> bool:
    if availability_enforcement_scope == "never":
        return False
    if availability_policy == "unknown_allowed":
        return False
    if availability_enforcement_scope == "always":
        return availability_policy != "unknown_allowed"
    if availability_policy == "must_be_open" and (
        (profile.typed_constraints or {}).get("availability_constraint") == "must_be_open"
        or is_opportunity_query(query, profile, mode=opportunity_query_detection)
    ):
        return True
    return (profile.typed_constraints or {}).get("availability_constraint") == "must_be_open"


def wide_then_hard_filter(
    docs: list[RetrievedDoc],
    *,
    query: str,
    profile: QueryProfile,
    freshness_max_months: int,
    min_relevance: float = 0.16,
) -> tuple[list[RetrievedDoc], RetrievalFilterStats]:
    stats = RetrievalFilterStats(candidate_count=len(docs))
    seen: set[str] = set()
    kept: list[RetrievedDoc] = []
    for doc in docs:
        url = normalize_url(doc.url)
        if not url:
            stats.filtered_count += 1
            stats.low_signal_count += 1
            continue
        if url in seen:
            continue
        seen.add(url)

        text = _doc_text(doc)
        if len(text.split()) < 12:
            stats.filtered_count += 1
            stats.low_signal_count += 1
            continue

        rel = relevance_score(
            doc,
            query=query,
            facets=profile.domain_facets,
        )
        if rel < min_relevance:
            stats.filtered_count += 1
            stats.off_topic_count += 1
            continue

        fresh_flag, doc_date = freshness_ok(doc, max_months=freshness_max_months)
        if fresh_flag is False:
            stats.filtered_count += 1
            stats.stale_count += 1
            continue

        open_status = detect_open_status(text)
        meta = dict(doc.meta or {})
        meta.update(
            {
                "relevance_score": round(rel, 3),
                "freshness_ok": fresh_flag,
                "detected_open_status": open_status,
            }
        )
        if doc_date:
            meta["detected_document_date"] = doc_date.date().isoformat()
        kept.append(doc.model_copy(update={"url": url, "meta": meta}))

    stats.kept_count = len(kept)
    stats.filtered_count = max(stats.filtered_count, max(0, stats.candidate_count - stats.kept_count))
    return kept, stats


def corroboration_count(doc: RetrievedDoc, peers: list[RetrievedDoc]) -> int:
    doc_domain = normalized_domain(doc.url)
    doc_tokens = _tokenize(f"{doc.title} {doc.snippet}")
    count = 1
    for peer in peers:
        if peer is doc:
            continue
        peer_domain = normalized_domain(peer.url)
        if not peer_domain or peer_domain == doc_domain:
            continue
        overlap = len(doc_tokens & _tokenize(f"{peer.title} {peer.snippet}"))
        if overlap >= 2:
            count += 1
    return count


def verify_claim(
    *,
    claim_id: str,
    doc: RetrievedDoc,
    peers: list[RetrievedDoc],
    query_profile: QueryProfile,
    query: str,
    availability_policy: str,
    availability_enforcement_scope: str = "intent_triggered",
    opportunity_query_detection: str = "auto",
    freshness_max_months: int,
    verification_min_sources_per_claim: int,
    require_primary_or_official_proof: bool,
) -> ClaimVerificationResult:
    reason_codes: list[str] = []
    rel_score = relevance_score(doc, query=query, facets=query_profile.domain_facets)
    if rel_score < 0.16:
        return ClaimVerificationResult(
            claim_id=claim_id,
            status="withheld",
            reason_codes=["off_topic"],
            corroboration_count=0,
            primary_or_official=is_primary_or_official(doc),
            freshness_ok=None,
            open_status="unknown",
            relevance_score=rel_score,
        )

    fresh_flag, _ = freshness_ok(doc, max_months=freshness_max_months)
    if fresh_flag is False:
        reason_codes.append("stale_source")

    open_status = detect_open_status(_doc_text(doc))
    needs_open = query_requires_open_availability(
        query_profile,
        availability_policy=availability_policy,
        availability_enforcement_scope=availability_enforcement_scope,
        opportunity_query_detection=opportunity_query_detection,
        query=query,
    )
    if needs_open:
        if open_status == "closed":
            reason_codes.append("missing_open_status")
        elif open_status == "unknown":
            reason_codes.append("open_status_unknown")
        if not has_deadline_or_cycle_date(doc):
            reason_codes.append("missing_deadline_or_cycle_date")

    constraints = dict(query_profile.typed_constraints or {})
    full_text = f"{doc.title} {doc.snippet} {doc.content}".lower()
    location_constraint = str(constraints.get("location_constraint", "")).strip()
    if location_constraint and not _constraint_match(full_text, location_constraint):
        reason_codes.append("missing_location_match")
    eligibility_constraint = str(constraints.get("eligibility_constraint", "")).strip()
    if eligibility_constraint and not _constraint_match(full_text, eligibility_constraint):
        reason_codes.append("missing_eligibility_match")

    corroboration = corroboration_count(doc, peers)
    has_primary = is_primary_or_official(doc)
    if require_primary_or_official_proof and not has_primary:
        reason_codes.append("missing_primary_or_official_proof")
    if corroboration < max(1, verification_min_sources_per_claim):
        if not (require_primary_or_official_proof and has_primary):
            reason_codes.append("single_source_only")

    status = "verified"
    if any(code in {"stale_source", "missing_open_status", "off_topic"} for code in reason_codes):
        status = "withheld"
    elif reason_codes:
        status = "constrained"

    return ClaimVerificationResult(
        claim_id=claim_id,
        status=status,
        reason_codes=list(dict.fromkeys(reason_codes)),
        corroboration_count=corroboration,
        primary_or_official=has_primary,
        freshness_ok=fresh_flag,
        open_status=open_status,
        relevance_score=rel_score,
    )
