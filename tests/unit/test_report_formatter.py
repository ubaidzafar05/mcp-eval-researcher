from core.models import Citation
from core.report_formatter import (
    build_constrained_actionable_report,
    build_fail_closed_report,
    format_report_with_sources,
)


def test_report_formatter_replaces_sources_with_full_rows():
    report = (
        "## Executive Summary\nSummary.\n\n"
        "## Sources Used\n"
        "- [C1] placeholder"
    )
    citations = [
        Citation(
            claim_id="C1",
            source_url="https://example.com/a",
            title="Source A",
            provider="tavily",
            evidence="Evidence A",
        )
    ]
    formatted, cleaned = format_report_with_sources(
        report, citations, source_policy="external_only"
    )
    assert len(cleaned) == 1
    assert "## Sources Used" in formatted
    assert "## Evidence Confidence Summary" not in formatted
    assert "### Sources Snapshot" in formatted
    assert "### Full Source Ledger (Detailed Table)" in formatted
    assert "| Claim | Title | Provider | Tier | Confidence | URL | Evidence |" in formatted
    assert "https://example.com/a" in formatted
    assert "placeholder" not in formatted


def test_fail_closed_report_is_explicitly_non_factual():
    report = build_fail_closed_report("test query", reason="No external sources.")
    assert "Insufficient external evidence" in report
    assert "No factual findings are provided" in report
    assert "## How This Research Was Done" in report
    assert "## Detailed Source Analysis" in report
    assert "## Scenario Outlook" in report
    assert "## 12-Month Action Plan" in report


def test_constrained_report_uses_academic_structure_when_requested():
    report = build_constrained_actionable_report(
        "Prompt engineering as representation steering",
        reason="Weak source corroboration",
        reason_codes=["verification_floor"],
        report_structure_mode="academic_17",
    )
    assert "## Abstract" in report
    assert "## Methodology" in report
    assert "## Appendices" in report
