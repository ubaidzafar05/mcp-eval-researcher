from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from core.citations import dedupe_citations
from core.models import Citation, EvalResult, TenantContext
from core.query_profile import profile_query
from core.report_formatter import (
    build_constrained_actionable_report,
    format_report_with_sources,
)
from core.report_quality import (
    collect_missing_required_sections,
    detect_placeholder_content,
    ensure_required_sections,
)
from graph.nodes.eval_gate import create_eval_gate_node
from graph.nodes.hitl import HITLInputProvider, create_hitl_node
from graph.nodes.planner import create_planner_node
from graph.nodes.research_ddg import create_research_ddg_node
from graph.nodes.research_firecrawl import create_research_firecrawl_node
from graph.nodes.research_pool import create_research_pool_node
from graph.nodes.research_tavily import create_research_tavily_node
from graph.nodes.self_correction import create_self_correction_node
from graph.nodes.sub_research import create_sub_research_node
from graph.nodes.synthesizer import create_synthesizer_node
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _build_tenant_context(runtime: GraphRuntime) -> TenantContext:
    return TenantContext(
        tenant_id=runtime.config.tenant_id,
        org_id=runtime.config.tenant_org_id,
        user_id=runtime.config.tenant_user_id,
        quota_tier=runtime.config.tenant_quota_tier,
        rate_limits={
            "queries_per_hour": runtime.config.tenant_queries_per_hour,
            "tokens_per_day": runtime.config.tenant_tokens_per_day,
        },
    )


def _scoped_run_id(run_id: str, tenant_context: TenantContext | None) -> str:
    if tenant_context is None:
        return run_id
    tenant_id = (tenant_context.tenant_id or "").strip()
    if not tenant_id or tenant_id == "default":
        return run_id
    return f"{tenant_id}/{run_id}"


def build_initial_state(query: str, runtime: GraphRuntime) -> ResearchState:
    now = datetime.now(tz=UTC).isoformat()
    run_id = f"run-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    return {
        "run_id": run_id,
        "query": query,
        "started_at": now,
        "status": "started",
        "logs": [f"Run started at {now}"],
        "tasks": [],
        "subtopics": [],
        "shared_corpus_docs": [],
        "sub_reports": [],
        "subtopic_failures": [],
        "subtopic_metrics": {},
        "query_profile": profile_query(
            query,
            dual_use_depth=runtime.config.dual_use_depth,
            cleanup_mode=runtime.config.query_cleanup_mode,
        ),
        "tavily_docs": [],
        "ddg_docs": [],
        "firecrawl_docs": [],
        "tavily_retrieval_stats": {},
        "ddg_retrieval_stats": {},
        "firecrawl_retrieval_stats": {},
        "context_docs": [],
        "memory_docs": [],
        "provider_alerts": [],
        "source_index": {},
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
        "tenant_context": _build_tenant_context(runtime),
    }


def _minimal_distributed_state(
    query: str,
    *,
    run_id: str,
    status: str,
    started_at: str,
    final_report: str = "",
    logs: list[str] | None = None,
    citations: list[dict] | list[Citation] | None = None,
    eval_result: dict | None = None,
    artifacts_path: str = "",
) -> ResearchState:
    parsed_citations = [
        c if isinstance(c, Citation) else Citation.model_validate(c)
        for c in (citations or [])
    ]
    return {
        "run_id": run_id,
        "query": query,
        "started_at": started_at,
        "status": status,
        "logs": logs or [],
        "tasks": [],
        "subtopics": [],
        "shared_corpus_docs": [],
        "sub_reports": [],
        "subtopic_failures": [],
        "subtopic_metrics": {},
        "tavily_docs": [],
        "ddg_docs": [],
        "firecrawl_docs": [],
        "tavily_retrieval_stats": {},
        "ddg_retrieval_stats": {},
        "firecrawl_retrieval_stats": {},
        "context_docs": [],
        "memory_docs": [],
        "provider_alerts": [],
        "source_index": {},
        "report_draft": final_report,
        "final_report": final_report,
        "citations": parsed_citations,
        "eval_result": EvalResult.model_validate(eval_result or {}),
        "correction_count": 0,
        "needs_correction": False,
        "low_confidence": False,
        "firecrawl_requested": False,
        "hitl_decision": "accept",
        "hitl_retry_used": False,
        "metrics": {},
        "artifacts_path": artifacts_path,
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


def _dispatch_subresearch(state: ResearchState):
    subtopics = list(state.get("subtopics", []))
    if not subtopics:
        return "synthesizer"
    sends: list[Send] = []
    for item in subtopics:
        as_dict = item if isinstance(item, dict) else {}
        subtopic_id = getattr(item, "id", None) or str(as_dict.get("id", "")).strip()
        subtopic_query = getattr(item, "sub_query", None) or str(as_dict.get("sub_query", "")).strip()
        subtopic_facet = getattr(item, "facet", None) or str(as_dict.get("facet", "")).strip()
        if not subtopic_id or not subtopic_query:
            continue
        sends.append(
            Send(
                "sub_research",
                {
                    "run_id": state.get("run_id", ""),
                    "query": state.get("query", ""),
                    "query_profile": state.get("query_profile"),
                    "shared_corpus_docs": state.get("shared_corpus_docs", []),
                    "subtopics": state.get("subtopics", []),
                    "tenant_context": state.get("tenant_context"),
                    "subtopic_id": subtopic_id,
                    "subtopic_query": subtopic_query,
                    "subtopic_facet": subtopic_facet,
                },
            )
        )
    if not sends:
        return "synthesizer"
    return sends


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
    def _inject_method_trace_summary(report_body: str, summary: dict[str, object]) -> str:
        body = report_body.strip()
        if not body:
            return body
        method_lines = [
            "- Execution lanes used: "
            + ", ".join(
                lane
                for lane, used in (summary.get("lanes_run") or {}).items()
                if used
            ),
            "- Provider contribution mix: "
            + ", ".join(
                f"{provider}={count}"
                for provider, count in (summary.get("provider_mix") or {}).items()
            ),
            "- Source tier mix: "
            + ", ".join(
                f"{tier}={count}"
                for tier, count in (summary.get("source_tier_mix") or {}).items()
            ),
            f"- Low-trust supporting sources retained: {summary.get('dropped_low_quality_count', 0)}",
            f"- Planned tasks executed: {summary.get('task_count', 0)}",
        ]
        method_block = "\n".join(line for line in method_lines if line and not line.endswith(": "))
        if "## How This Research Was Done" in body:
            return body.replace(
                "## How This Research Was Done",
                "## How This Research Was Done\n" + method_block + "\n",
                1,
            )
        return body

    def finalize_node(state: ResearchState) -> dict:
        citations = dedupe_citations(state.get("citations", []))
        report = ensure_required_sections(
            state.get("report_draft", ""),
            allow_placeholder_sections=(
                runtime.config.allow_placeholder_sections
                and runtime.config.report_completion_mode == "template_fill"
            ),
        )
        missing_sections = collect_missing_required_sections(
            report,
            report_structure_mode=runtime.config.report_structure_mode,
        )
        placeholder_hits = detect_placeholder_content(report)
        fail_closed_marker = "insufficient external evidence is available to produce a reliable deep-research report"
        fail_closed_report = fail_closed_marker in report.lower()
        if runtime.config.report_completion_mode == "strict_no_placeholders":
            if (missing_sections or placeholder_hits) and not fail_closed_report:
                failure_reasons: list[str] = []
                if missing_sections:
                    failure_reasons.append(
                        "missing_sections:" + ",".join(missing_sections[:4])
                    )
                if placeholder_hits:
                    failure_reasons.append(
                        "placeholder_content:" + ",".join(placeholder_hits[:3])
                    )
                report = build_constrained_actionable_report(
                    state["query"],
                    reason=(
                        "Finalize blocked because the draft failed strict section/placeholder integrity checks."
                    ),
                    reason_codes=failure_reasons,
                    citations=citations,
                    report_structure_mode=runtime.config.report_structure_mode,
                )
                metrics = dict(state.get("metrics", {}))
                metrics["quality_failure_buckets"] = list(
                    dict.fromkeys(
                        [
                            *list(metrics.get("quality_failure_buckets", [])),
                            *(
                                ["placeholder_content"]
                                if placeholder_hits
                                else []
                            ),
                            *(
                                ["top_section_directness"]
                                if missing_sections
                                else []
                            ),
                        ]
                    )
                )
                metrics["constrained_reason_codes"] = list(
                    dict.fromkeys(
                        [
                            *list(metrics.get("constrained_reason_codes", [])),
                            *failure_reasons,
                        ]
                    )
                )
                metrics["quality_verdict"] = "constrained"
                metrics["placeholder_content_detected"] = bool(placeholder_hits)
                state["metrics"] = metrics
        report, citations = format_report_with_sources(
            report,
            citations,
            source_policy=runtime.config.source_policy,
            report_presentation=runtime.config.report_presentation,
            sources_presentation=runtime.config.sources_presentation,
            show_technical_sections_default=runtime.config.show_technical_sections_default,
            report_surface_mode=runtime.config.report_surface_mode,
            report_structure_mode=runtime.config.report_structure_mode,
            max_sources_snapshot=runtime.config.max_sources_snapshot,
        )
        run_id = state["run_id"]
        tenant_context = state.get("tenant_context")

        decision = state.get("hitl_decision", "accept")
        if decision == "abort":
            status = "aborted"
        elif state.get("low_confidence", False):
            status = "completed_low_confidence"
        else:
            status = "completed"

        provider_mix: dict[str, int] = {}
        for citation in citations:
            provider = (citation.provider or "unknown").strip().lower()
            provider_mix[provider] = provider_mix.get(provider, 0) + 1
        tier_mix = {
            "A": sum(1 for c in citations if (c.source_tier or "").upper() == "A"),
            "B": sum(1 for c in citations if (c.source_tier or "").upper() == "B"),
            "C": sum(1 for c in citations if (c.source_tier or "").upper() == "C"),
        }
        method_trace_summary = {
            "lanes_run": {
                "tavily": len(state.get("tavily_docs", [])) > 0,
                "ddg": len(state.get("ddg_docs", [])) > 0,
                "firecrawl": len(state.get("firecrawl_docs", [])) > 0,
                "research_pool": len(state.get("shared_corpus_docs", [])) > 0,
                "sub_research": len(state.get("sub_reports", [])) > 0,
            },
            "provider_mix": provider_mix,
            "source_tier_mix": tier_mix,
            "dropped_low_quality_count": int(tier_mix.get("C", 0)),
            "task_count": len(state.get("tasks", [])),
        }
        report = _inject_method_trace_summary(report, method_trace_summary)
        metrics = dict(state.get("metrics", {}))
        metrics["method_trace_summary"] = method_trace_summary
        metrics.setdefault("placeholder_content_detected", bool(placeholder_hits))
        subtopic_reason_codes = list(state.get("subtopic_failures", []))
        metrics.setdefault("subtopic_count", len(state.get("subtopics", [])))
        metrics.setdefault("subtopic_success_count", len(state.get("sub_reports", [])))
        metrics.setdefault(
            "subtopic_failed_count",
            max(0, metrics["subtopic_count"] - metrics["subtopic_success_count"]),
        )
        metrics.setdefault("subtopic_reason_codes", subtopic_reason_codes)
        metrics.setdefault("merge_conflicts_detected", 0)
        if "editor_input_word_count" not in metrics:
            editor_text = "\n\n".join(item.content for item in state.get("sub_reports", []))
            metrics["editor_input_word_count"] = len(editor_text.split())
        scoped_run_id = _scoped_run_id(run_id, tenant_context)
        out_dir: Path | None = None
        artifact_error: str | None = None
        try:
            out_file = runtime.mcp_client.call_local_tool(
                "write_report_output",
                scoped_run_id,
                report,
            )
            out_dir = Path(out_file).parent
            citations_payload = [c.model_dump() for c in citations]
            eval_dump = (state.get("eval_result") or EvalResult()).model_dump()
            (out_dir / "citations.json").write_text(
                json.dumps(citations_payload, indent=2, ensure_ascii=True), encoding="utf-8"
            )
            (out_dir / "eval.json").write_text(
                json.dumps(eval_dump, indent=2, ensure_ascii=True), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - exercised via integration env pressure
            artifact_error = f"artifact_write_failed:{exc}"
        except Exception as exc:  # noqa: BLE001
            artifact_error = f"artifact_write_failed:{exc}"

        try:
            runtime.memory_store.add_run(
                run_id=run_id,
                query=state["query"],
                summary=report[:3500],
                citations=citations,
            )
        except Exception as exc:  # noqa: BLE001
            artifact_error = artifact_error or f"memory_store_write_failed:{exc}"

        runtime.tracer.event(
            run_id,
            "finalize",
            "Run finalized",
            payload={
                "status": status,
                "output_dir": str(out_dir) if out_dir else "",
                "artifact_error": artifact_error or "",
            },
        )
        finalize_logs = [f"Finalized run with status={status}."]
        if artifact_error:
            finalize_logs.append(f"Artifacts degraded: {artifact_error}")
            metrics["artifact_write_failed"] = True
            metrics["artifact_error"] = artifact_error
        return {
            "final_report": report,
            "citations": citations,
            "status": status,
            "artifacts_path": str(out_dir) if out_dir else "",
            "metrics": metrics,
            "logs": finalize_logs,
        }

    return finalize_node


def build_graph(
    runtime: GraphRuntime,
    hitl_input_provider: HITLInputProvider | None = None,
):
    builder = StateGraph(ResearchState)

    planner = create_planner_node(runtime)
    research_pool = create_research_pool_node(runtime)
    tavily = create_research_tavily_node(runtime)
    ddg = create_research_ddg_node(runtime)
    firecrawl = create_research_firecrawl_node(runtime)
    sub_research = create_sub_research_node(runtime)
    synthesizer = create_synthesizer_node(runtime)
    self_correction = create_self_correction_node(runtime)
    eval_gate = create_eval_gate_node(runtime)
    hitl = create_hitl_node(runtime, input_provider=hitl_input_provider)
    self_correction_retry = create_self_correction_retry_node(runtime)
    finalize = create_finalize_node(runtime)

    builder.add_node("planner", planner)
    builder.add_node("research_pool", research_pool)
    builder.add_node("research_tavily", tavily)
    builder.add_node("research_ddg", ddg)
    builder.add_node("research_firecrawl", firecrawl)
    builder.add_node("sub_research", sub_research)
    builder.add_node("synthesizer", synthesizer)
    builder.add_node("self_correction", self_correction)
    builder.add_node("eval_gate", eval_gate)
    builder.add_node("hitl", hitl)
    builder.add_node("self_correction_retry", self_correction_retry)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "planner")
    if runtime.config.subtopic_mode == "map_reduce":
        builder.add_edge("planner", "research_pool")
        builder.add_conditional_edges("research_pool", _dispatch_subresearch)
        builder.add_edge("sub_research", "synthesizer")
    else:
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
    distributed: bool = False,
) -> ResearchState:
    """
    Run the research graph.

    Args:
        query: The research query.
        runtime: The graph runtime context.
        hitl_input_provider: Optional provider for HITL input.
        distributed: If True, dispatch to Celery worker (blocks until complete).
    """
    if distributed:
        if not runtime.config.enable_distributed:
            started_at = datetime.now(tz=UTC).isoformat()
            return _minimal_distributed_state(
                query,
                run_id="disabled-distributed-run",
                status="failed",
                started_at=started_at,
                final_report="Distributed execution is disabled by runtime profile/config.",
                logs=["Distributed mode is disabled; rerun with inline mode or enable distributed profile."],
            )
        from graph.distributed import (
            dispatch_distributed_task,
            is_distributed_ready,
            wait_for_distributed_result,
        )

        started_at = datetime.now(tz=UTC).isoformat()
        print(f"Dispatching distributed task for query: {query}")
        ready, reason = is_distributed_ready(
            timeout_seconds=runtime.config.distributed_health_timeout_seconds
        )
        if not ready:
            return _minimal_distributed_state(
                query,
                run_id="failed-distributed-run",
                status="failed",
                started_at=started_at,
                final_report="Distributed execution is unavailable.",
                logs=[f"Distributed readiness check failed: {reason}"],
            )

        task = dispatch_distributed_task(
            query=query,
            run_id=None,
            tenant_id=runtime.config.tenant_id,
        )

        print(f"Task dispatched (ID: {task.id}). Waiting for results...")
        try:
            result_dict = wait_for_distributed_result(
                task,
                queue_wait_seconds=runtime.config.distributed_queue_wait_seconds,
                result_timeout_seconds=15,
            )

            # Reconstruct a partial ResearchState from the result to satisfy the return type
            # The result_dict is a dumped implementation of ResearchResult

            # We need to map ResearchResult back to ResearchState structure if possible,
            # or minimally provide what's needed.
            # ResearchResult has: run_id, query, final_report, citations, eval_result, etc.

            return _minimal_distributed_state(
                result_dict.get("query", query),
                run_id=result_dict.get("run_id", "distributed-run"),
                status=result_dict.get("status", "completed"),
                started_at=started_at,
                final_report=result_dict.get("final_report", ""),
                citations=result_dict.get("citations", []),
                eval_result=result_dict.get("eval_result", {}),
                logs=[f"Distributed run completed via Celery task {task.id}"],
                artifacts_path=result_dict.get("artifacts_path", ""),
            )

        except Exception as e:
            # Handle timeout or execution errors
            print(f"Distributed task failed: {e}")
            return _minimal_distributed_state(
                query,
                run_id="failed-distributed-run",
                status="failed",
                started_at=started_at,
                final_report=f"Error during distributed execution: {str(e)}",
                logs=[f"Distributed task failed: {str(e)}"],
            )

    # Local synchronous execution
    graph = build_graph(runtime, hitl_input_provider=hitl_input_provider)
    initial_state = build_initial_state(query, runtime)
    final_state = graph.invoke(initial_state)
    return final_state
