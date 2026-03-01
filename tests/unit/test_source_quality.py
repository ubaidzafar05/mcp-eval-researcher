from core.models import RetrievedDoc
from core.source_quality import (
    clean_evidence_text,
    prioritize_docs,
    source_tier,
)


def _doc(url: str, title: str, snippet: str, score: float = 0.6) -> RetrievedDoc:
    return RetrievedDoc(
        provider="tavily",
        title=title,
        url=url,
        snippet=snippet,
        content=snippet,
        score=score,
    )


def test_source_tier_classification():
    assert source_tier("https://arxiv.org/abs/1234.5678", "tavily", "paper") == "A"
    assert source_tier("https://reuters.com/world/test", "ddg", "news") == "B"
    assert source_tier("https://random-blog-example.com/post", "tavily", "blog") == "C"
    assert source_tier("https://example.edu/news/article", "ddg", "campus news") == "B"
    assert source_tier("https://example.edu/admissions/ai-ms", "ddg", "AI MS admissions") == "A"


def test_clean_evidence_text_strips_boilerplate():
    raw = "Privacy Policy\\nTerms of Use\\nThis is the real evidence sentence about detection quality."
    cleaned = clean_evidence_text(raw, max_chars=160)
    assert "Privacy Policy" not in cleaned
    assert "real evidence sentence" in cleaned


def test_prioritize_docs_prefers_tier_ab_under_high_confidence():
    docs = [
        _doc("https://random-blog-example.com/post", "blog", "low confidence source", 0.9),
        _doc("https://arxiv.org/abs/1234.5678", "paper", "peer reviewed evidence", 0.5),
        _doc("https://reuters.com/world/test", "news", "reputable report", 0.4),
    ]
    prioritized = prioritize_docs(
        docs,
        source_quality_bar="high_confidence",
        min_tier_ab_sources=2,
    )
    tiers = [str((doc.meta or {}).get("source_tier")) for doc in prioritized[:2]]
    assert tiers[0] in {"A", "B"}
    assert tiers[1] in {"A", "B"}


def test_prioritize_docs_deprioritizes_social_sources():
    docs = [
        _doc("https://instagram.com/reel/some-video", "reel", "short social clip", 0.95),
        _doc("https://arxiv.org/abs/1234.5678", "paper", "peer reviewed evidence", 0.5),
    ]
    prioritized = prioritize_docs(
        docs,
        source_quality_bar="high_confidence",
        min_tier_ab_sources=1,
    )
    assert "arxiv.org" in prioritized[0].url
