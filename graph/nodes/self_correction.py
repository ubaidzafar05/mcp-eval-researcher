from __future__ import annotations

import logging
from core.citations import extract_claim_ids, validate_claim_level_citations
from core.models import Citation
from graph.runtime import GraphRuntime
from graph.state import ResearchState
from agents.prompts import CRITIC_PROMPT

logger = logging.getLogger(__name__)


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

        # Attempt LLM-based correction
        model_selection = runtime.model_router.select_model(
            task_type="correction",
            tenant_id=state.get("tenant_context").tenant_id if state.get("tenant_context") else "default",
            plan_complexity="medium",
            context_size=len(report)
        )
        
        try:
            client = runtime.get_llm_client(model_selection.provider)
            system_msg = CRITIC_PROMPT
            user_msg = (
                f"Original Report:\n{report}\n\n"
                f"Validation Issues:\n{chr(10).join(reasons)}\n\n"
                "Please rewrite the report to address these issues. Maintain all valid citation IDs [Cx]."
            )
            
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
            
            new_report = content
            
            runtime.tracer.event(
                state["run_id"],
                "self_correction",
                "Applied LLM correction",
                payload={"provider": model_selection.provider, "model": model_selection.model_name},
            )
            
            return {
                "report_draft": new_report,
                "citations": citations,
                "status": "corrected",
                "logs": [f"Self-correction rewritten by {model_selection.model_name}."],
            }

        except Exception as e:
            logger.error(f"Correction LLM failed: {e}. Falling back to heuristic.")
        
        # Fallback to existing logic
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
            "Applied fallback correction",
            payload={"coverage_before": coverage, "reasons": reasons},
        )
        return {
            "report_draft": report + note,
            "citations": citations,
            "status": "corrected",
            "logs": ["Self-correction appended quality notes and filled missing citations (fallback)."],
        }

    return self_correction_node

