from __future__ import annotations

import re
from collections import Counter

from core.models import QueryProfile

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}")
WHITESPACE_PATTERN = re.compile(r"\s+")

STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "and",
    "are",
    "because",
    "before",
    "being",
    "between",
    "both",
    "can",
    "could",
    "does",
    "each",
    "from",
    "have",
    "here",
    "into",
    "more",
    "much",
    "only",
    "other",
    "over",
    "same",
    "should",
    "some",
    "than",
    "that",
    "the",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "with",
    "would",
    "your",
    "want",
    "everything",
    "thing",
    "stuff",
    "dig",
    "find",
    "tell",
    "explain",
}

FILLER_PHRASES = (
    "everything you can",
    "dig up",
    "tell me",
    "can you",
    "i want",
    "all about",
    "as much as possible",
)

COMMON_MISSPELLINGS = {
    "reltionship": "relationship",
    "querry": "query",
    "funtionality": "functionality",
    "reseach": "research",
}

DUAL_USE_TERMS = {
    "bypass",
    "bypassing",
    "evade",
    "evasion",
    "circumvent",
    "jailbreak",
    "exploit",
    "attack",
    "undetectable",
    "avoid detection",
}

HIGH_RISK_PATTERNS = (
    "how to bypass",
    "how can i bypass",
    "step by step bypass",
    "make it undetectable",
    "evade detector",
    "circumvent filter",
)

TIME_KEYWORDS = (
    "current",
    "currently",
    "latest",
    "today",
    "this year",
    "upcoming",
    "open now",
    "active intake",
)

AVAILABILITY_KEYWORDS = (
    "currently available",
    "available now",
    "open now",
    "applications open",
    "active intake",
    "accepting applications",
)

OPPORTUNITY_KEYWORDS = (
    "scholarship",
    "fellowship",
    "grant",
    "admission",
    "admissions",
    "apply",
    "application",
    "deadline",
    "intake",
    "open now",
    "currently available",
    "funded",
    "vacancy",
    "job opening",
)

PHRASE_FACETS = (
    "quantum physics",
    "machine learning",
    "artificial intelligence",
    "content moderation",
    "ai detection",
    "deep learning",
)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_PATTERN.findall(text or "")]


def normalize_query_text(query: str, *, mode: str = "aggressive") -> str:
    q = (query or "").strip()
    if not q:
        return ""
    lowered = q.lower()
    for wrong, fixed in COMMON_MISSPELLINGS.items():
        lowered = re.sub(rf"\b{re.escape(wrong)}\b", fixed, lowered)
    if mode == "aggressive":
        for phrase in FILLER_PHRASES:
            lowered = lowered.replace(phrase, " ")
    elif mode == "light":
        for phrase in ("tell me", "can you", "i want"):
            lowered = lowered.replace(phrase, " ")
    normalized = WHITESPACE_PATTERN.sub(" ", lowered).strip(" .,!?:;")
    return normalized or q.strip()


def _extract_facets(query: str, *, mode: str = "aggressive", limit: int = 8) -> list[str]:
    q_l = (query or "").lower()
    facets: list[str] = []
    for phrase in PHRASE_FACETS:
        if phrase in q_l:
            facets.append(phrase)
    tokens = [t for t in _tokenize(q_l) if t not in STOPWORDS]
    if mode == "aggressive":
        tokens = [t for t in tokens if len(t) >= 4]
    counts = Counter(tokens)
    for token, _ in counts.most_common(limit * 2):
        if token not in facets:
            facets.append(token)
        if len(facets) >= limit:
            break
    return facets[:limit]


def _extract_typed_constraints(original_query: str, normalized_query: str, facets: list[str]) -> dict[str, str]:
    original = (original_query or "").strip()
    normalized = (normalized_query or "").strip().lower()
    constraints: dict[str, str] = {}

    if facets:
        constraints["subject"] = ", ".join(facets[:3])

    title_entities = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", original)
    if title_entities:
        constraints["entity"] = ", ".join(dict.fromkeys(title_entities[:4]))

    if any(token in normalized for token in TIME_KEYWORDS):
        constraints["time_constraint"] = "recency_required"
    else:
        year_hits = re.findall(r"\b(20\d{2})\b", normalized)
        if year_hits:
            constraints["time_constraint"] = f"year={year_hits[-1]}"

    if any(token in normalized for token in AVAILABILITY_KEYWORDS):
        constraints["availability_constraint"] = "must_be_open"

    location_match = re.search(
        r"\bfor\s+([a-z][a-z\s'/-]{2,40})\s+(?:student|students|citizen|citizens|applicant|applicants)\b",
        normalized,
    )
    if location_match:
        constraints["location_constraint"] = location_match.group(1).strip()

    eligibility_match = re.search(
        r"\bfor\s+([a-z0-9\s'/-]{3,60})\b",
        normalized,
    )
    if eligibility_match:
        constraints["eligibility_constraint"] = eligibility_match.group(1).strip()

    if not constraints.get("entity") and " of " in normalized:
        rhs = normalized.split(" of ", 1)[1].strip()
        if rhs:
            constraints["entity"] = rhs[:80]

    return constraints


def _must_have_fields(constraints: dict[str, str]) -> list[str]:
    fields = ["source_url", "evidence_excerpt"]
    if "time_constraint" in constraints:
        fields.append("published_or_updated_date")
    if constraints.get("availability_constraint") == "must_be_open":
        fields.extend(["open_status", "deadline_or_intake_date"])
    if "location_constraint" in constraints:
        fields.append("location_match")
    if "eligibility_constraint" in constraints:
        fields.append("eligibility_match")
    return list(dict.fromkeys(fields))


def profile_query(
    query: str,
    *,
    dual_use_depth: str = "dynamic_defensive",
    cleanup_mode: str = "aggressive",
) -> QueryProfile:
    raw = (query or "").strip()
    normalized = normalize_query_text(raw, mode=cleanup_mode)
    q_l = normalized.lower()
    facets = _extract_facets(normalized, mode=cleanup_mode)
    typed_constraints = _extract_typed_constraints(raw, normalized, facets)
    must_have_evidence_fields = _must_have_fields(typed_constraints)

    has_dual_use = any(term in q_l for term in DUAL_USE_TERMS)
    high_risk = any(pattern in q_l for pattern in HIGH_RISK_PATTERNS)

    if has_dual_use:
        intent = "security_dual_use"
    elif " vs " in q_l or "compare" in q_l or "difference" in q_l:
        intent = "comparative"
    elif any(term in q_l for term in ("error", "issue", "debug", "not working", "fail")):
        intent = "diagnostic"
    elif any(term in q_l for term in ("build", "implement", "deploy", "setup", "architecture")):
        intent = "operational"
    else:
        intent = "explanatory"

    risk_band = "high" if high_risk else "medium" if has_dual_use else "low"

    if dual_use_depth == "dynamic_strict" and has_dual_use:
        risk_band = "high"

    return QueryProfile(
        intent_type=intent,
        domain_facets=facets,
        risk_band=risk_band,
        dual_use=has_dual_use,
        original_query=raw,
        normalized_query=normalized,
        typed_constraints=typed_constraints,
        must_have_evidence_fields=must_have_evidence_fields,
    )


def safe_analysis_policy(profile: QueryProfile, *, dual_use_depth: str) -> str:
    if not profile.dual_use:
        return "standard"
    if dual_use_depth == "dynamic_strict":
        return "strict_defensive"
    if dual_use_depth == "dynamic_balanced":
        return "balanced_defensive"
    return "defensive"


def requires_open_availability(profile: QueryProfile) -> bool:
    value = (profile.typed_constraints or {}).get("availability_constraint", "")
    return value == "must_be_open"


def is_opportunity_query(
    query: str,
    profile: QueryProfile,
    *,
    mode: str = "auto",
) -> bool:
    if mode == "off":
        return False

    typed = dict(profile.typed_constraints or {})
    if typed.get("availability_constraint") == "must_be_open":
        return True

    lowered = (query or profile.normalized_query or profile.original_query or "").lower()
    hits = sum(1 for marker in OPPORTUNITY_KEYWORDS if marker in lowered)
    if mode == "strict":
        return hits >= 2
    return hits >= 1
