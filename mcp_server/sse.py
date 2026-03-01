from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from rich.console import Console

console = Console()

NODE_STAGE = {
    "planner": ("planning", "Planning research tasks."),
    "research_pool": ("research", "Building shared evidence pool."),
    "research_tavily": ("research", "Collecting Tavily evidence."),
    "research_ddg": ("research", "Collecting DuckDuckGo evidence."),
    "research_firecrawl": ("research", "Collecting Firecrawl extraction."),
    "sub_research": ("research", "Running parallel subtopic analysis."),
    "synthesizer": ("synthesis", "Synthesizing report draft."),
    "self_correction": ("synthesis", "Applying self-correction pass."),
    "self_correction_retry": ("synthesis", "Running correction retry."),
    "eval_gate": ("evaluation", "Evaluating quality and citation coverage."),
    "hitl": ("evaluation", "Resolving confidence routing."),
    "finalize": ("finalizing", "Writing final artifacts."),
}


def _event_node(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") or {}
    if isinstance(metadata, dict):
        node = metadata.get("langgraph_node")
        if isinstance(node, str) and node:
            return node
    name = event.get("name")
    return name if isinstance(name, str) else ""


async def event_generator(
    events_iterable: AsyncGenerator[dict[str, Any], None]
) -> AsyncGenerator[str, None]:
    """Consumes a LangGraph event stream and yields SSE-formatted data."""
    final_emitted = False
    emitted_starts: set[str] = set()
    planned_subtopics = 0
    completed_subtopics = 0
    try:
        async for event in events_iterable:
            kind = event.get("event")
            node = _event_node(event)

            if kind == "on_chain_start" and node in NODE_STAGE and node not in emitted_starts:
                emitted_starts.add(node)
                stage, message = NODE_STAGE[node]
                payload = {"type": "status", "stage": stage, "message": message, "node": node}
                yield f"data: {json.dumps(payload)}\n\n"

            if kind == "on_custom_event":
                data = event.get("data", {})
                yield f"data: {json.dumps(data)}\n\n"

            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    payload = {"type": "token", "content": chunk.content}
                    yield f"data: {json.dumps(payload)}\n\n"

            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if not isinstance(output, dict):
                    continue
                provider_alerts = output.get("provider_alerts")
                if isinstance(provider_alerts, list) and provider_alerts:
                    payload = {
                        "type": "status",
                        "stage": "research",
                        "active_stage": "research",
                        "message": "Provider degradation detected; recovery path enabled.",
                        "reason_codes": [str(code) for code in provider_alerts],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                if node == "planner":
                    subtopics = output.get("subtopics")
                    if isinstance(subtopics, list) and subtopics:
                        planned_subtopics = len(subtopics)
                        payload = {
                            "type": "status",
                            "stage": "decomposition",
                            "message": f"Decomposed query into {planned_subtopics} subtopics.",
                            "subtopic_total": planned_subtopics,
                            "subtopic_completed": completed_subtopics,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                    continue
                if node == "sub_research":
                    completed_subtopics += 1
                    payload = {
                        "type": "status",
                        "stage": "fanout",
                        "message": (
                            f"Subtopic branch completed ({completed_subtopics}/"
                            f"{planned_subtopics or '?'})"
                        ),
                        "subtopic_total": planned_subtopics,
                        "subtopic_completed": completed_subtopics,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    continue
                if node == "synthesizer" and planned_subtopics > 0:
                    payload = {
                        "type": "status",
                        "stage": "merge",
                        "message": "Merging subtopic branches into final narrative.",
                        "subtopic_total": planned_subtopics,
                        "subtopic_completed": completed_subtopics,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                if "run_id" not in output:
                    continue
                report = output.get("final_report") or output.get("report_draft")
                if not isinstance(report, str) or not report.strip():
                    payload = {
                        "type": "status",
                        "stage": "finalizing",
                        "message": "Pipeline finished without final report payload.",
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    continue
                payload = {
                    "type": "status",
                    "stage": "final",
                    "data": {
                        "result": {
                            "run_id": output.get("run_id"),
                            "status": output.get("status", "completed"),
                            "final_report": report,
                            "artifacts_path": output.get("artifacts_path", ""),
                            "constrained_reason_codes": (
                                list((output.get("metrics") or {}).get("constrained_reason_codes", []))
                                if isinstance(output.get("metrics"), dict)
                                else []
                            ),
                            "subtopic_count": (
                                int((output.get("metrics") or {}).get("subtopic_count", 0))
                                if isinstance(output.get("metrics"), dict)
                                else 0
                            ),
                            "subtopic_success_count": (
                                int((output.get("metrics") or {}).get("subtopic_success_count", 0))
                                if isinstance(output.get("metrics"), dict)
                                else 0
                            ),
                            "subtopic_failed_count": (
                                int((output.get("metrics") or {}).get("subtopic_failed_count", 0))
                                if isinstance(output.get("metrics"), dict)
                                else 0
                            ),
                        }
                    },
                }
                final_emitted = True
                yield f"data: {json.dumps(payload)}\n\n"

    except Exception as exc:  # noqa: BLE001
        console.print_exception()
        err_payload = {"type": "error", "message": str(exc)}
        yield f"data: {json.dumps(err_payload)}\n\n"

    done_payload = {"type": "done", "final_emitted": final_emitted}
    yield f"data: {json.dumps(done_payload)}\n\n"
