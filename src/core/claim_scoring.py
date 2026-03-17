from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from core.models import RetrievedDoc
from core.source_quality import clean_evidence_text


@dataclass
class ClaimAssessment:
    claim_id: str
    score: float
    status: Literal["asserted", "constrained", "withheld"]
    reasons: list[str]


TIER_WEIGHT = {
    "A": 0.9,
    "B": 0.75,
    "C": 0.45,
    "unknown": 0.3,
}


def _tier_of_doc(doc: RetrievedDoc) -> str:
    tier = str((doc.meta or {}).get("source_tier") or "unknown").upper()
    return tier if tier in {"A", "B", "C"} else "unknown"


def _confidence_bonus(doc: RetrievedDoc) -> float:
    conf = str((doc.meta or {}).get("confidence") or "unknown").lower()
    if conf == "high":
        return 0.1
    if conf == "medium":
        return 0.04
    if conf == "low":
        return -0.02
    return -0.05


def _snippet_quality(doc: RetrievedDoc) -> float:
    snippet = clean_evidence_text(doc.snippet or doc.content, max_chars=260)
    words = re.findall(r"\b[\w'-]+\b", snippet)
    if len(words) < 8:
        return -0.08
    if len(words) > 24:
        return 0.04
    return 0.0


def score_claim(
    *,
    claim_id: str,
    doc: RetrievedDoc,
    corroboration_count: int,
    contradiction_penalty: float,
    relevance_score: float,
    min_assert_score: float,
) -> ClaimAssessment:
    tier_weight = TIER_WEIGHT.get(_tier_of_doc(doc), 0.3)
    score = (
        tier_weight
        + _confidence_bonus(doc)
        + min(0.15, 0.04 * max(0, corroboration_count - 1))
        + max(-0.2, min(0.15, relevance_score - 0.5))
        + _snippet_quality(doc)
        - contradiction_penalty
    )
    score = max(0.0, min(1.0, score))

    reasons: list[str] = []
    tier = _tier_of_doc(doc)
    reasons.append(f"tier={tier}")
    reasons.append(f"corroboration={corroboration_count}")
    if contradiction_penalty > 0:
        reasons.append(f"contradiction_penalty={contradiction_penalty:.2f}")

    if score >= min_assert_score:
        status: Literal["asserted", "constrained", "withheld"] = "asserted"
    elif score >= (min_assert_score - 0.17):
        status = "constrained"
    else:
        status = "withheld"
    return ClaimAssessment(claim_id=claim_id, score=score, status=status, reasons=reasons)
