from core.citations import (
    citation_coverage,
    dedupe_citations,
    filter_citations_by_policy,
    validate_claim_level_citations,
    validate_source_integrity,
)
from core.models import Citation


def test_citation_coverage_and_validation():
    report = "Finding one [C1]. Finding two [C2]."
    citations = [
        Citation(claim_id="C1", source_url="https://a"),
        Citation(claim_id="C2", source_url="https://b"),
    ]
    coverage = citation_coverage(report, citations)
    ok, reasons, measured = validate_claim_level_citations(
        report, citations, min_coverage=0.85
    )
    assert coverage == 1.0
    assert ok is True
    assert reasons == []
    assert measured == 1.0


def test_citation_dedupe_and_external_policy_filtering():
    citations = [
        Citation(claim_id="C1", source_url="https://a.com/path", provider="tavily"),
        Citation(claim_id="C1", source_url="https://a.com/path", provider="tavily"),
        Citation(claim_id="C2", source_url="", provider="memory"),
    ]
    deduped = dedupe_citations(citations)
    assert len(deduped) == 2

    external_only = filter_citations_by_policy(
        deduped, source_policy="external_only"
    )
    assert len(external_only) == 1
    assert external_only[0].provider == "tavily"


def test_source_integrity_rejects_non_external_and_missing_diversity():
    citations = [
        Citation(claim_id="C1", source_url="https://a.com", provider="tavily"),
        Citation(claim_id="C2", source_url="", provider="memory"),
    ]
    ok, reasons, stats = validate_source_integrity(
        citations,
        source_policy="external_only",
        min_external_sources=2,
        min_unique_providers=2,
    )
    assert ok is False
    assert stats["unique_external_urls"] == 1
    assert any("external_only" in reason for reason in reasons)


def test_source_integrity_enforces_tier_ab_and_corroboration():
    citations = [
        Citation(
            claim_id="C1",
            source_url="https://random-blog-example.com/post",
            provider="tavily",
            source_tier="C",
        ),
    ]
    ok, reasons, _ = validate_source_integrity(
        citations,
        source_policy="external_only",
        min_external_sources=1,
        min_unique_providers=1,
        min_tier_ab_sources=1,
        require_corroboration_for_tier_c=True,
    )
    assert ok is False
    assert any("Tier A/B" in reason for reason in reasons)
