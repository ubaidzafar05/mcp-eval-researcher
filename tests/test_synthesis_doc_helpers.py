"""Tests for core.synthesis.doc_helpers - written BEFORE the module exists (test-first)."""
from __future__ import annotations

from core.models import QueryProfile, RetrievedDoc
from core.synthesis.doc_helpers import (
    best_text,
    build_analytical_fallback,
    derive_lens,
    doc_tier,
    evidence_summary,
    is_citable_external_doc,
    unique_docs_by_url,
)


def _make_doc(
    url: str = "https://example.com/article",
    provider: str = "tavily",
    title: str = "Test Article",
    snippet: str = "First sentence. Second sentence.",
    content: str = "",
    meta: dict | None = None,
) -> RetrievedDoc:
    return RetrievedDoc(
        url=url,
        provider=provider,
        title=title,
        snippet=snippet,
        content=content,
        score=0.8,
        meta=meta or {},
    )


def _make_profile(**kwargs) -> QueryProfile:
    defaults = dict(
        original_query="test query",
        normalized_query="test query",
        intent_type="explanatory",
        risk_band="low",
        domain_facets=["performance", "security"],
        typed_constraints={},
        must_have_evidence_fields=[],
    )
    defaults.update(kwargs)
    return QueryProfile(**defaults)


class TestBestText:
    def test_returns_first_sentence_from_content(self):
        doc = _make_doc(content="Main insight here. More detail follows.")
        result = best_text(doc)
        assert "Main insight here" in result

    def test_falls_back_to_provider_when_empty(self):
        doc = _make_doc(content="", snippet="")
        result = best_text(doc)
        assert "tavily" in result.lower()

    def test_returns_full_text_when_no_period(self):
        doc = _make_doc(content="", snippet="No period here at all")
        result = best_text(doc)
        assert result == "No period here at all"


class TestIsCitableExternalDoc:
    def test_tavily_with_url_is_citable(self):
        doc = _make_doc(url="https://example.com/article", provider="tavily")
        assert is_citable_external_doc(doc) is True

    def test_memory_provider_is_not_citable(self):
        doc = _make_doc(url="https://example.com/article", provider="memory")
        assert is_citable_external_doc(doc) is False

    def test_missing_url_is_not_citable(self):
        doc = _make_doc(url="", provider="tavily")
        assert is_citable_external_doc(doc) is False


class TestUniqueDocsByUrl:
    def test_deduplicates_same_url(self):
        docs = [_make_doc(url="https://example.com/a"), _make_doc(url="https://example.com/a")]
        result = unique_docs_by_url(docs)
        assert len(result) == 1

    def test_keeps_different_urls(self):
        docs = [_make_doc(url="https://a.com/x"), _make_doc(url="https://b.com/y")]
        result = unique_docs_by_url(docs)
        assert len(result) == 2

    def test_skips_docs_with_no_url(self):
        docs = [_make_doc(url=""), _make_doc(url="https://good.com/page")]
        result = unique_docs_by_url(docs)
        assert len(result) == 1


class TestDocTier:
    def test_uses_meta_tier_first(self):
        doc = _make_doc(meta={"source_tier": "A"})
        assert doc_tier(doc) == "A"

    def test_falls_back_to_source_tier_inference(self):
        doc = _make_doc(url="https://arxiv.org/paper", provider="tavily", meta={})
        result = doc_tier(doc)
        assert result in {"A", "B", "C", "unknown"}

    def test_unknown_for_invalid_tier(self):
        doc = _make_doc(meta={"source_tier": "Z"})
        assert doc_tier(doc) == "unknown"


class TestEvidenceSummary:
    def test_counts_tiers_correctly(self):
        docs = [
            _make_doc(meta={"source_tier": "A"}),
            _make_doc(meta={"source_tier": "A"}),
            _make_doc(meta={"source_tier": "B"}),
            _make_doc(meta={"source_tier": "C"}),
        ]
        a, b, c, total = evidence_summary(docs)
        assert a == 2
        assert b == 1
        assert c == 1
        assert total == 4


class TestDeriveLens:
    def test_matches_domain_facet(self):
        profile = _make_profile(domain_facets=["security", "performance"])
        doc = _make_doc(snippet="security vulnerability in the system")
        result = derive_lens(profile, doc)
        assert "Security" in result

    def test_fallback_for_benchmark(self):
        profile = _make_profile(domain_facets=[])
        doc = _make_doc(snippet="evaluation benchmark results show gains")
        result = derive_lens(profile, doc)
        assert "Benchmark" in result

    def test_default_fallback(self):
        profile = _make_profile(domain_facets=[])
        doc = _make_doc(snippet="some unrelated content")
        result = derive_lens(profile, doc)
        assert result == "Core Technical Signal"


class TestBuildAnalyticalFallback:
    def test_empty_docs_returns_fail_closed(self):
        report, citations, index = build_analytical_fallback("test query", [])
        assert "## Executive Summary" in report or "No citable" in report
        assert citations == []
        assert index == {}

    def test_with_docs_produces_7_sections(self):
        docs = [_make_doc(url=f"https://example.com/{i}") for i in range(3)]
        report, citations, index = build_analytical_fallback("test query", docs)
        for section in [
            "Executive Summary",
            "Key Findings",
            "Recommendations",
            "Risks, Gaps, and Uncertainty",
            "How This Research Was Done",
            "Counterevidence",
            "Sources Used",
        ]:
            assert section in report, f"Missing section: {section}"

    def test_citations_built_from_docs(self):
        docs = [_make_doc(url=f"https://example.com/{i}") for i in range(3)]
        _, citations, index = build_analytical_fallback("test query", docs)
        assert len(citations) == 3
        assert len(index) == 3
