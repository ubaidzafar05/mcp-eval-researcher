from __future__ import annotations

import re
from dataclasses import dataclass

NEGATION_MARKERS = {
    "no evidence",
    "not supported",
    "contradicts",
    "unlikely",
    "debunked",
    "false",
    "weak evidence",
}

AFFIRM_MARKERS = {
    "supports",
    "indicates",
    "shows",
    "demonstrates",
    "evidence suggests",
    "corroborates",
}


@dataclass
class ContradictionReport:
    contradiction_count: int
    examples: list[str]
    penalty: float


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def detect_contradictions(statements: list[str]) -> ContradictionReport:
    normalized = [_normalize(s) for s in statements if (s or "").strip()]
    contradictions = 0
    examples: list[str] = []

    for idx, a in enumerate(normalized):
        a_neg = any(marker in a for marker in NEGATION_MARKERS)
        a_aff = any(marker in a for marker in AFFIRM_MARKERS)
        if not (a_neg or a_aff):
            continue
        for b in normalized[idx + 1 :]:
            shared_tokens = set(a.split()) & set(b.split())
            if len(shared_tokens) < 4:
                continue
            b_neg = any(marker in b for marker in NEGATION_MARKERS)
            b_aff = any(marker in b for marker in AFFIRM_MARKERS)
            if (a_neg and b_aff) or (a_aff and b_neg):
                contradictions += 1
                if len(examples) < 4:
                    examples.append(
                        f"Potential contradiction between: '{a[:110]}' and '{b[:110]}'"
                    )
    penalty = min(0.25, contradictions * 0.05)
    return ContradictionReport(
        contradiction_count=contradictions,
        examples=examples,
        penalty=penalty,
    )
