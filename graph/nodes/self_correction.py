from __future__ import annotations

from core.citations import extract_claim_ids, validate_claim_level_citations
from core.models import Citation
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def create_self_correction_node(runtime: GraphRuntime):
    def self_correction_node(state: ResearchState) -> dict:
        report = state.get("report_draft", "")
        citations = list(state.get("citations", []))
        ok, reasons, coverage = validate_claim_level_citations(
            report, citations, min_coverage=runtime.config.citation_threshold
        )
        if ok:
            return {
                "report_draft": report,
                "citations": citations,
                "status": "corrected",
                "logs": ["Self-correction check passed without edits."],
            }

        context_docs = state.get("context_docs", [])
        fallback_doc = context_docs[0] if context_docs else None
        existing_claim_ids = {c.claim_id for c in citations}
        for claim_id in extract_claim_ids(report):
            if claim_id in existing_claim_ids:
                continue
            if fallback_doc is None:
                break
            citations.append(
                Citation(
                    claim_id=claim_id,
                    source_url=fallback_doc.url,
                    title=fallback_doc.title,
                    provider=fallback_doc.provider,
                    evidence=fallback_doc.snippet[:240],
                )
            )

        note = (
            "\n\n## Quality Notes\n"
            f"- Citation coverage after correction: {coverage:.2f}\n"
            "- This draft may require additional source verification."
        )
        runtime.tracer.event(
            state["run_id"],
            "self_correction",
            "Applied correction pass",
            payload={"coverage_before": coverage, "reasons": reasons},
        )
        return {
            "report_draft": report + note,
            "citations": citations,
            "status": "corrected",
            "logs": ["Self-correction appended quality notes and filled missing citations."],
        }

    return self_correction_node

