from core.citations import citation_coverage, validate_claim_level_citations
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

