from core.report_quality import (
    assess_report_quality,
    collect_missing_required_sections,
    detect_placeholder_content,
    ensure_required_sections,
)


def test_report_quality_accepts_structured_research_report():
    report = """
## Executive Summary
In short, this report explains how stronger retrieval and citation discipline improve output trustworthiness in practical systems. The answer is that reliability rises when evidence quality is prioritized, uncertainty is stated explicitly, and claims are cross-checked against independent sources [C1] [C2].

## Direct Answer
In short, verified findings show stronger retrieval and citation discipline improve trustworthiness because claim support is clearer.
Constrained: some findings still rely on single-source support and need corroboration.
Unknowns: evidence freshness and unresolved contradictions can still limit certainty.

## Key Findings
- [C1] Retrieval pipelines improve factual grounding because source quality is high.
- [C2] Latency and cost tradeoffs require model/tool routing by task type; this indicates orchestration design matters.
- [C3] Evaluation gates reduce unsupported claims in final outputs, which implies better decision reliability.

## Verified Findings Register
| Claim ID | Status | Why | Evidence Summary | Sources |
|---|---|---|---|---|
| [C1] | verified | corroborated by independent sources | Retrieval quality materially improves grounding | https://example.com/source-1 |
| [C2] | verified | corroborated by independent sources | Routing by task type lowers quality regressions | https://example.com/source-2 |
| [C3] | constrained | single-source support | Evaluation gate effect needs broader corroboration | https://example.com/source-3 |

## 12-Month Action Plan
- Q1: tighten citation policies.
- Q2: expand provider diversity.
- Q3: add evaluation regressions.
- Q4: publish reliability benchmarks.

## Risks, Gaps, and Uncertainty
- Source freshness can drift for rapidly changing tooling.
- However, some claims still depend on single-source evidence.

## Recommendations
- Add recency checks for time-sensitive claims.
- Maintain claim-level citation checks before publishing reports.

## Sources Used
- [C1] Source one (tavily) - https://example.com/source-1
- [C2] Source two (ddg) - https://example.com/source-2
- [C3] Source three (firecrawl) - https://example.com/source-3
"""
    ok, reasons, metrics = assess_report_quality(
        report,
        depth="balanced",
        min_words=90,
        min_claims=3,
        min_required_sections=8,
    )
    assert ok is True
    assert reasons == []
    assert int(metrics["claim_count"]) >= 3


def test_report_quality_rejects_generic_short_output():
    report = "RAG is useful. It helps accuracy sometimes."
    ok, reasons, _ = assess_report_quality(
        report,
        min_words=50,
        min_claims=2,
        min_required_sections=4,
    )
    assert ok is False
    assert any("brief" in reason.lower() for reason in reasons)
    assert any("structure" in reason.lower() for reason in reasons)


def test_ensure_required_sections_keeps_draft_without_injecting_placeholders():
    draft = """
## Scope and Method
- Simple method.

## Key Findings
- [C1] Claim one.

## Recommendations
- Do X.
"""
    normalized = ensure_required_sections(draft)
    assert normalized.lstrip().startswith("## Scope and Method")
    assert "https://example.com" not in normalized
    missing = collect_missing_required_sections(normalized)
    assert "executive summary" in missing
    assert "direct answer" in missing


def test_placeholder_detection_catches_fake_register_rows():
    report = """
## Executive Summary
This report summarizes evidence collected from available sources.

## Verified Findings Register
| Claim ID | Status | Why | Evidence Summary | Sources |
|---|---|---|---|---|
| [C1] | constrained | Missing verification floor | Pending stronger corroboration | https://example.com |
"""
    hits = detect_placeholder_content(report)
    assert "example_com_placeholder_domain" in hits
    assert "verified_register_placeholder_row" in hits


def test_report_quality_accepts_academic_17_contract_when_sections_present():
    report = """
## Abstract
This paper analyzes prompt engineering as representation steering [C1], because prompt structure changes internal activations in measurable ways.

## Introduction
Prompting is widely used but weakly formalized in practice [C2], therefore a formal controllability framing is required.

## Theoretical Framework
We model prompting as conditional control in latent activation space [C3], which implies representation steering can be quantified.

## Literature Review
Prior work covers in-context learning, interpretability, and optimization [C4], however links between these strands remain incomplete.

## Hypotheses
H1-H4 define measurable activation and robustness effects [C5], and suggest specific falsifiable pathways.

## Methodology
We evaluate open and closed models, compare baseline vs prompted states, and compute controlled metrics [C6] to isolate causal prompt effects.

## Metrics & Evaluation
Accuracy, calibration error, hallucination rate, and latent drift are measured [C7], because controllability must be validated under perturbation.

## Formal Modeling of Prompting
Prompting is treated as low-rank perturbation over activation trajectories [C8], suggesting constrained latent search equivalence.

## Empirical Results
Results indicate reliable activation shifts and controllability tradeoffs [C9], but unknown edge cases remain for long contexts.

## Generalization & Scaling Laws
Performance trends vary by model size and context length under fixed token budgets [C10], indicating scaling nonlinearity.

## Theoretical Contributions
We define prompting as a conditional control operator with testable implications [C11], therefore theory and practice align more closely.

## Practical Contributions
A prompt stability index and brittleness metrics are proposed for operations [C12], which enables safer deployment decisions.

## Limitations
API opacity and stochastic sampling constrain internal observability [C13], and uncertainty remains around hidden alignment layers.

## Ethical & Governance Considerations
Safety bypass and manipulation risks require governance controls [C14], because representation steering has dual-use implications.

## Future Research Directions
Meta-prompting and representation surgery are promising extensions [C15], however reproducibility standards are still evolving.

## Conclusion
Prompt engineering can be formalized with measurable control and boundary conditions [C16], while unknown failure modes require continuous monitoring.

## Appendices
Proof sketches, extended tables, and additional ablations are included.

## Sources Used
- [C1] https://example.com/s1
- [C2] https://example.com/s2
- [C3] https://example.com/s3
"""
    ok, reasons, _ = assess_report_quality(
        report,
        query="Prompt engineering as representation steering in large language models",
        depth="balanced",
        min_words=180,
        min_claims=10,
        report_structure_mode="academic_17",
        top_section_min_verified_claims=2,
    )
    assert ok is True
    assert reasons == []
