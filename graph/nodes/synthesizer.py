from __future__ import annotations

from core.models import Citation, RetrievedDoc
from core.pruning import prune_context_docs
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _best_text(doc: RetrievedDoc) -> str:
    text = (doc.content or doc.snippet or "").strip()
    return text.split(".")[0].strip() if "." in text else text


def create_synthesizer_node(runtime: GraphRuntime):
    def synthesizer_node(state: ResearchState) -> dict:
        all_docs = (
            state.get("memory_docs", [])
            + state.get("tavily_docs", [])
            + state.get("ddg_docs", [])
            + state.get("firecrawl_docs", [])
        )
        context_docs = prune_context_docs(
            all_docs,
            per_doc_tokens=runtime.config.per_doc_tokens,
            total_tokens=runtime.config.total_context_tokens,
        )
        if not context_docs:
            report = (
                "## Executive Summary\n"
                "Insufficient source context was collected to produce a high-confidence report.\n\n"
                "## Findings\n"
                "- [C1] No reliable external sources were returned for this query.\n"
            )
            citations = [
                Citation(
                    claim_id="C1",
                    source_url="",
                    title="No source available",
                    provider="fallback",
                    evidence="No source context was available.",
                )
            ]
            return {
                "report_draft": report,
                "context_docs": [],
                "citations": citations,
                "status": "synthesized",
                "logs": ["Synthesizer generated fallback report."],
            }

        findings: list[str] = []
        citations: list[Citation] = []
        for i, doc in enumerate(context_docs[:6], start=1):
            claim_id = f"C{i}"
            claim_text = _best_text(doc) or f"Source insight from {doc.provider}."
            findings.append(f"- [{claim_id}] {claim_text}")
            citations.append(
                Citation(
                    claim_id=claim_id,
                    source_url=doc.url,
                    title=doc.title,
                    provider=doc.provider,
                    evidence=doc.snippet[:240] or claim_text[:240],
                )
            )

        report = (
            "## Executive Summary\n"
            f"Research synthesis for: **{state['query']}**\n\n"
            "## Findings\n"
            f"{chr(10).join(findings)}\n\n"
            "## Recommendations\n"
            "- Prioritize claims supported by multiple sources.\n"
            "- Validate time-sensitive facts before external publication.\n"
        )
        runtime.tracer.event(
            state["run_id"],
            "synthesizer",
            "Draft report created",
            payload={"citations": len(citations), "context_docs": len(context_docs)},
        )
        return {
            "context_docs": context_docs,
            "report_draft": report,
            "citations": citations,
            "status": "synthesized",
            "logs": [f"Synthesizer created report with {len(citations)} claim citations."],
        }

    return synthesizer_node

