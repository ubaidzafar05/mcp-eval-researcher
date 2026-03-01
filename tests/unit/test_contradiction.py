from core.contradiction import detect_contradictions


def test_detect_contradictions_finds_conflict():
    statements = [
        "Evidence suggests the relationship is strongly supported by controlled studies.",
        "There is no evidence and the relationship is not supported by controlled studies.",
    ]
    report = detect_contradictions(statements)
    assert report.contradiction_count >= 1
    assert report.penalty > 0


def test_detect_contradictions_no_conflict_when_aligned():
    statements = [
        "Evidence suggests the claim requires more validation.",
        "Evidence suggests uncertainty remains and further validation is required.",
    ]
    report = detect_contradictions(statements)
    assert report.contradiction_count == 0
