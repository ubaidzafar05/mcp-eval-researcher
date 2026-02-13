from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from core.models import EvalResult
from graph.nodes.eval_gate import create_eval_gate_node
from graph.nodes.hitl import HITLInputProvider, create_hitl_node
from graph.nodes.planner import create_planner_node
from graph.nodes.research_ddg import create_research_ddg_node
from graph.nodes.research_firecrawl import create_research_firecrawl_node
from graph.nodes.research_tavily import create_research_tavily_node
from graph.nodes.self_correction import create_self_correction_node
from graph.nodes.synthesizer import create_synthesizer_node
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def build_initial_state(query: str) -> ResearchState:
    now = datetime.now(tz=UTC).isoformat()
    run_id = f"run-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    return {
        "run_id": run_id,
        "query": query,
        "started_at": now,
        "status": "started",
        "logs": [f"Run started at {now}"],
        "tasks": [],
        "tavily_docs": [],
        "ddg_docs": [],
        "firecrawl_docs": [],
        "context_docs": [],
        "memory_docs": [],
        "report_draft": "",
        "final_report": "",
        "citations": [],
        "eval_result": EvalResult(),
        "correction_count": 0,
        "needs_correction": False,
        "low_confidence": False,
        "firecrawl_requested": False,
        "hitl_decision": "accept",
        "hitl_retry_used": False,
        "metrics": {},
        "artifacts_path": "",
    }


def _route_after_eval(state: ResearchState) -> str:
    eval_result = state.get("eval_result")
    if eval_result and eval_result.pass_gate:
        return "finalize"
    if state.get("needs_correction", False):
        return "self_correction_retry"
    return "hitl"


def _route_after_hitl(state: ResearchState) -> str:
    decision = state.get("hitl_decision", "accept_with_warning")
    if decision == "retry":
        return "self_correction_retry"
    return "finalize"


def create_self_correction_retry_node(runtime: GraphRuntime):
    base = create_self_correction_node(runtime)

    def retry_node(state: ResearchState) -> dict:
        next_count = int(state.get("correction_count", 0)) + 1
        updates = base(state)
        updates["correction_count"] = next_count
        existing_logs = list(updates.get("logs", []))
        updates["logs"] = [f"Correction retry pass #{next_count}."] + existing_logs
        return updates

    return retry_node


def create_finalize_node(runtime: GraphRuntime):
    def finalize_node(state: ResearchState) -> dict:
        report = state.get("report_draft", "")
        run_id = state["run_id"]
        out_file = runtime.mcp_client.call_local_tool("write_report_output", run_id, report)
        out_dir = Path(out_file).parent
        citations = [c.model_dump() for c in state.get("citations", [])]
        eval_dump = (state.get("eval_result") or EvalResult()).model_dump()
        (out_dir / "citations.json").write_text(
            json.dumps(citations, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        (out_dir / "eval.json").write_text(
            json.dumps(eval_dump, indent=2, ensure_ascii=True), encoding="utf-8"
        )

        runtime.memory_store.add_run(
            run_id=run_id,
            query=state["query"],
            summary=report[:3500],
            citations=state.get("citations", []),
        )

        decision = state.get("hitl_decision", "accept")
        if decision == "abort":
            status = "aborted"
        elif state.get("low_confidence", False):
            status = "completed_low_confidence"
        else:
            status = "completed"

        runtime.tracer.event(
            run_id,
            "finalize",
            "Run finalized",
            payload={"status": status, "output_dir": str(out_dir)},
        )
        return {
            "final_report": report,
            "status": status,
            "artifacts_path": str(out_dir),
            "logs": [f"Finalized run with status={status}."],
        }

    return finalize_node


def build_graph(
    runtime: GraphRuntime,
    hitl_input_provider: HITLInputProvider | None = None,
):
    builder = StateGraph(ResearchState)

    planner = create_planner_node(runtime)
    tavily = create_research_tavily_node(runtime)
    ddg = create_research_ddg_node(runtime)
    firecrawl = create_research_firecrawl_node(runtime)
    synthesizer = create_synthesizer_node(runtime)
    self_correction = create_self_correction_node(runtime)
    eval_gate = create_eval_gate_node(runtime)
    hitl = create_hitl_node(runtime, input_provider=hitl_input_provider)
    self_correction_retry = create_self_correction_retry_node(runtime)
    finalize = create_finalize_node(runtime)

    builder.add_node("planner", planner)
    builder.add_node("research_tavily", tavily)
    builder.add_node("research_ddg", ddg)
    builder.add_node("research_firecrawl", firecrawl)
    builder.add_node("synthesizer", synthesizer)
    builder.add_node("self_correction", self_correction)
    builder.add_node("eval_gate", eval_gate)
    builder.add_node("hitl", hitl)
    builder.add_node("self_correction_retry", self_correction_retry)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "research_tavily")
    builder.add_edge("planner", "research_ddg")
    builder.add_edge("planner", "research_firecrawl")
    builder.add_edge("research_tavily", "synthesizer")
    builder.add_edge("research_ddg", "synthesizer")
    builder.add_edge("research_firecrawl", "synthesizer")
    builder.add_edge("synthesizer", "self_correction")
    builder.add_edge("self_correction", "eval_gate")
    builder.add_edge("self_correction_retry", "eval_gate")

    builder.add_conditional_edges(
        "eval_gate",
        _route_after_eval,
        {
            "finalize": "finalize",
            "self_correction_retry": "self_correction_retry",
            "hitl": "hitl",
        },
    )
    builder.add_conditional_edges(
        "hitl",
        _route_after_hitl,
        {
            "self_correction_retry": "self_correction_retry",
            "finalize": "finalize",
        },
    )
    builder.add_edge("finalize", END)
    return builder.compile()


def run_graph(
    query: str,
    runtime: GraphRuntime,
    hitl_input_provider: HITLInputProvider | None = None,
) -> ResearchState:
    graph = build_graph(runtime, hitl_input_provider=hitl_input_provider)
    initial_state = build_initial_state(query)
    final_state = graph.invoke(initial_state)
    return final_state

