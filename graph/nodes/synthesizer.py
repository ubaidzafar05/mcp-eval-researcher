from __future__ import annotations

import json
from core.models import Citation, RetrievedDoc
from core.pruning import prune_context_docs
from graph.runtime import GraphRuntime
from graph.state import ResearchState
from agents.prompts import SYNTHESIZER_PROMPT


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

        # Prepare Prompt
        import logging
        logger = logging.getLogger(__name__)
        
        system_msg = SYNTHESIZER_PROMPT
        user_msg = (
            f"Query: {state['query']}\n\n"
            "Context:\n"
        )
        for i, doc in enumerate(context_docs[:8], start=1):
            user_msg += f"Source [C{i}]: {doc.title}\n{doc.snippet}\n\n"

        # Route Model
        model_selection = runtime.model_router.select_model(
            task_type="synthesis", 
            tenant_id=state.get("tenant_context").tenant_id if state.get("tenant_context") else "default",
            plan_complexity="high" # Assume high for synthesis
        )
        
        logger.info(f"Synthesizer routed to: {model_selection.provider}/{model_selection.model_name}")

        try:
            client = runtime.get_llm_client(model_selection.provider)
            
            # This is a simplified adapter. In a real app complexity would be in a shared LLM adapter service.
            content = ""
            if model_selection.provider == "openai" or model_selection.provider == "groq":
                resp = client.chat.completions.create(
                    model=model_selection.model_name,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=model_selection.temperature
                )
                content = resp.choices[0].message.content
            elif model_selection.provider == "anthropic":
                resp = client.messages.create(
                    model=model_selection.model_name,
                    max_tokens=4000,
                    system=system_msg,
                    messages=[
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=model_selection.temperature
                )
                content = resp.content[0].text
            
            report = content
            
            # Extract citations from LLM report
            from core.citations import extract_claim_ids
            citations = []
            used_claim_ids = extract_claim_ids(report)
            for claim_id in used_claim_ids:
                # claim_id is like "C1", "C2"
                try:
                    idx = int(claim_id[1:]) - 1 # 0-indexed
                    if 0 <= idx < len(context_docs):
                        doc = context_docs[idx]
                        citations.append(
                            Citation(
                                claim_id=claim_id,
                                source_url=doc.url,
                                title=doc.title,
                                provider=doc.provider,
                                evidence=doc.snippet[:200]
                            )
                        )
                except ValueError:
                    continue

        except Exception as e:
            logger.error(f"Synthesizer LLM failed: {e}. Falling back to stub.")
            # Fallback to logic-based generation
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
                "\n*(Note: Report generated via fallback logic due to LLM error)*"
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

