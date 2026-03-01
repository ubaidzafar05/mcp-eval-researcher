from core.claim_scoring import score_claim
from core.models import RetrievedDoc


def _doc(tier: str, confidence: str, provider: str = "tavily") -> RetrievedDoc:
    return RetrievedDoc(
        provider=provider,  # type: ignore[arg-type]
        title="Test source",
        url="https://example.org/source",
        snippet="This source provides methodological evidence and corroborated findings.",
        content="This source provides methodological evidence and corroborated findings.",
        score=0.82,
        meta={"source_tier": tier, "confidence": confidence},
    )


def test_claim_scoring_asserted_for_strong_support():
    assessment = score_claim(
        claim_id="C1",
        doc=_doc("A", "high"),
        corroboration_count=3,
        contradiction_penalty=0.0,
        relevance_score=0.82,
        min_assert_score=0.62,
    )
    assert assessment.status == "asserted"
    assert assessment.score >= 0.62


def test_claim_scoring_withheld_for_weak_support():
    assessment = score_claim(
        claim_id="C2",
        doc=_doc("C", "low", provider="ddg"),
        corroboration_count=1,
        contradiction_penalty=0.15,
        relevance_score=0.35,
        min_assert_score=0.62,
    )
    assert assessment.status in {"constrained", "withheld"}
    assert assessment.score < 0.7
