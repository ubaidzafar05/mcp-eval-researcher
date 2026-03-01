from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from core.config import load_config
from core.pruning import optional_dependency_status, startup_reason_codes
from core.runtime_profile import dependency_health
from graph.pipeline import build_graph, build_initial_state
from graph.runtime import GraphRuntime
from main import run_research
from mcp_server.sse import event_generator

app = FastAPI(title="Cloud Hive API", version="0.1.0")


_GRAPH_NODE_STAGE: dict[str, str] = {
    "planner": "planning",
    "research_pool": "research",
    "research_tavily": "research",
    "research_ddg": "research",
    "research_firecrawl": "research",
    "sub_research": "research",
    "synthesizer": "synthesis",
    "self_correction": "synthesis",
    "self_correction_retry": "synthesis",
    "eval_gate": "evaluation",
    "hitl": "evaluation",
    "finalize": "finalizing",
}
_VALID_STREAM_STAGES = {"planning", "research", "synthesis", "evaluation", "finalizing", "final"}


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    execution_mode: Literal["auto", "inline", "distributed"] = "inline"
    runtime_profile: Literal["minimal", "balanced", "full"] | None = None
    startup_guard_mode: Literal["hybrid", "strict"] | None = None
    subtopic_mode: Literal["disabled", "map_reduce"] | None = None
    subtopic_count_default: int | None = None
    subtopic_count_max: int | None = None
    subreport_failure_policy: Literal["continue_constrained", "retry_once", "fail_closed"] | None = None
    mcp_mode: str | None = None
    mcp_transport: str | None = None
    judge_provider: str | None = None
    judge_json_mode: Literal["repair_retry_fallback", "strict", "heuristic"] | None = None
    research_mode: Literal["fast", "balanced", "peak"] | None = None
    fact_mode: Literal["strict", "balanced", "open_web"] | None = None
    crawl_strategy: Literal["wide_then_filter", "dual_lane", "aggressive"] | None = None
    availability_policy: Literal["must_be_open", "recent_or_open", "unknown_allowed"] | None = None
    freshness_max_months: int | None = None
    verification_min_sources_per_claim: int | None = None
    primary_source_policy: Literal["strict", "hybrid", "broad"] | None = None
    report_style: Literal["brief_appendix", "full_narrative", "decision_dashboard"] | None = None
    report_presentation: Literal["book", "standard"] | None = None
    sources_presentation: Literal["cards_with_ledger", "ledger_only"] | None = None
    show_raw_source_ledger_default: bool | None = None
    method_narrative_enabled: bool | None = None
    show_technical_sections_default: bool | None = None
    report_completion_mode: Literal["strict_no_placeholders", "template_fill"] | None = None
    tier_policy_mode: Literal["primary_only_strict", "hybrid_strict", "broad"] | None = None
    report_structure_mode: Literal["decision_brief", "academic_17"] | None = None
    availability_enforcement_scope: Literal["intent_triggered", "always", "never"] | None = None
    opportunity_query_detection: Literal["auto", "strict", "off"] | None = None
    report_surface_mode: Literal["decision_brief_only", "brief_plus_confidence", "full_technical"] | None = None
    top_section_min_verified_claims: int | None = None
    insight_density_min: int | None = None
    report_voice_mode: Literal["analyst", "neutral"] | None = None
    min_primary_verified_findings: int | None = None
    truth_mode: Literal["strict", "balanced", "always_answer"] | None = None
    claim_policy: Literal["adaptive_scoring", "tier_first", "coverage_first"] | None = None
    evidence_floor_mode: Literal["adaptive", "fixed_high", "fixed_medium"] | None = None
    insufficient_evidence_output: Literal["constrained_actionable", "fail_closed", "soft_fallback"] | None = None
    query_cleanup_mode: Literal["aggressive", "light", "none"] | None = None
    narrative_citation_density: Literal["light_inline", "dense_inline", "footnote"] | None = None
    max_sources_snapshot: int | None = None
    source_quality_bar: Literal["high_confidence", "mixed", "broad"] | None = None
    dual_use_depth: Literal["dynamic_defensive", "dynamic_balanced", "dynamic_strict"] | None = None
    tenant_id: str = "default"
    tenant_org_id: str = "default-org"
    tenant_user_id: str = "default-user"
    tenant_quota_tier: str = "free"


def _request_overrides(request: ResearchRequest) -> dict:
    overrides: dict[str, object] = {
        "interactive_hitl": False,
        "tenant_id": request.tenant_id,
        "tenant_org_id": request.tenant_org_id,
        "tenant_user_id": request.tenant_user_id,
        "tenant_quota_tier": request.tenant_quota_tier,
    }
    if request.runtime_profile:
        overrides["runtime_profile"] = request.runtime_profile
    if request.startup_guard_mode:
        overrides["startup_guard_mode"] = request.startup_guard_mode
    if request.subtopic_mode:
        overrides["subtopic_mode"] = request.subtopic_mode
    if request.subtopic_count_default is not None:
        overrides["subtopic_count_default"] = request.subtopic_count_default
    if request.subtopic_count_max is not None:
        overrides["subtopic_count_max"] = request.subtopic_count_max
    if request.subreport_failure_policy:
        overrides["subreport_failure_policy"] = request.subreport_failure_policy
    if request.mcp_mode:
        overrides["mcp_mode"] = request.mcp_mode
    if request.mcp_transport:
        overrides["mcp_transport"] = request.mcp_transport
    if request.judge_provider:
        overrides["judge_provider"] = request.judge_provider
    if request.judge_json_mode:
        overrides["judge_json_mode"] = request.judge_json_mode
    if request.research_mode:
        overrides["research_mode"] = request.research_mode
    if request.fact_mode:
        overrides["fact_mode"] = request.fact_mode
    if request.crawl_strategy:
        overrides["crawl_strategy"] = request.crawl_strategy
    if request.availability_policy:
        overrides["availability_policy"] = request.availability_policy
    if request.freshness_max_months is not None:
        overrides["freshness_max_months"] = request.freshness_max_months
    if request.verification_min_sources_per_claim is not None:
        overrides["verification_min_sources_per_claim"] = request.verification_min_sources_per_claim
    if request.primary_source_policy:
        overrides["primary_source_policy"] = request.primary_source_policy
    if request.report_style:
        overrides["report_style"] = request.report_style
    if request.report_presentation:
        overrides["report_presentation"] = request.report_presentation
    if request.sources_presentation:
        overrides["sources_presentation"] = request.sources_presentation
    if request.show_raw_source_ledger_default is not None:
        overrides["show_raw_source_ledger_default"] = request.show_raw_source_ledger_default
    if request.method_narrative_enabled is not None:
        overrides["method_narrative_enabled"] = request.method_narrative_enabled
    if request.show_technical_sections_default is not None:
        overrides["show_technical_sections_default"] = request.show_technical_sections_default
    if request.report_completion_mode:
        overrides["report_completion_mode"] = request.report_completion_mode
    if request.tier_policy_mode:
        overrides["tier_policy_mode"] = request.tier_policy_mode
    if request.report_structure_mode:
        overrides["report_structure_mode"] = request.report_structure_mode
    if request.availability_enforcement_scope:
        overrides["availability_enforcement_scope"] = request.availability_enforcement_scope
    if request.opportunity_query_detection:
        overrides["opportunity_query_detection"] = request.opportunity_query_detection
    if request.report_surface_mode:
        overrides["report_surface_mode"] = request.report_surface_mode
    if request.top_section_min_verified_claims is not None:
        overrides["top_section_min_verified_claims"] = request.top_section_min_verified_claims
    if request.insight_density_min is not None:
        overrides["insight_density_min"] = request.insight_density_min
    if request.report_voice_mode:
        overrides["report_voice_mode"] = request.report_voice_mode
    if request.min_primary_verified_findings is not None:
        overrides["min_primary_verified_findings"] = request.min_primary_verified_findings
    if request.truth_mode:
        overrides["truth_mode"] = request.truth_mode
    if request.claim_policy:
        overrides["claim_policy"] = request.claim_policy
    if request.evidence_floor_mode:
        overrides["evidence_floor_mode"] = request.evidence_floor_mode
    if request.insufficient_evidence_output:
        overrides["insufficient_evidence_output"] = request.insufficient_evidence_output
    if request.query_cleanup_mode:
        overrides["query_cleanup_mode"] = request.query_cleanup_mode
    if request.narrative_citation_density:
        overrides["narrative_citation_density"] = request.narrative_citation_density
    if request.max_sources_snapshot is not None:
        overrides["max_sources_snapshot"] = request.max_sources_snapshot
    if request.source_quality_bar:
        overrides["source_quality_bar"] = request.source_quality_bar
    if request.dual_use_depth:
        overrides["dual_use_depth"] = request.dual_use_depth
    return overrides


def _should_use_distributed(
    query: str,
    execution_mode: str,
    *,
    distributed_enabled: bool,
    distributed_auto_enabled: bool = True,
) -> bool:
    if not distributed_enabled:
        return False
    if execution_mode == "inline":
        return False
    if execution_mode == "distributed":
        return True
    if not distributed_auto_enabled:
        return False
    query_l = query.lower()
    heavy_terms = (
        "deep research",
        "comprehensive",
        "benchmark",
        "compare",
        "multi-step",
        "detailed analysis",
    )
    return len(query) >= 280 or any(term in query_l for term in heavy_terms)


def _distributed_available() -> bool:
    try:
        from graph.distributed import execute_research_task  # type: ignore
    except Exception:
        return False
    return execute_research_task is not None


def _distributed_helpers():
    try:
        from graph.distributed import (
            dispatch_distributed_task,
            is_distributed_ready,
            wait_for_distributed_result,
        )
    except Exception:
        return None
    return {
        "dispatch": dispatch_distributed_task,
        "is_ready": is_distributed_ready,
        "wait_result": wait_for_distributed_result,
    }


def _startup_diagnostics(config) -> dict[str, object]:
    dependency_status = optional_dependency_status()
    reason_codes = startup_reason_codes(startup_guard_mode=config.startup_guard_mode)
    return {
        "optional_dependency_status": dependency_status,
        "startup_reason_codes": reason_codes,
        "startup_guard_mode": config.startup_guard_mode,
    }


async def _with_heartbeat(
    events_iterable,
    *,
    interval_seconds: float = 2.5,
    max_runtime_seconds: int = 900,
    warn_before_idle_ratio: float = 0.70,
    stage_idle_seconds: dict[str, int] | None = None,
):
    stage_idle_seconds = stage_idle_seconds or {
        "planning": 120,
        "research": 180,
        "synthesis": 420,
        "evaluation": 180,
        "finalizing": 180,
    }

    def _threshold(stage: str) -> int:
        candidate = int(stage_idle_seconds.get(stage, stage_idle_seconds.get("research", 180)))
        return max(1, candidate)

    def _resolve_stage_from_event(event: dict, current_stage: str) -> str:
        kind = str(event.get("event") or "")
        if kind == "on_custom_event":
            data = event.get("data") or {}
            if isinstance(data, dict):
                stage = str(data.get("stage") or "").strip().lower()
                if stage in _VALID_STREAM_STAGES:
                    return stage
                active_stage = str(data.get("active_stage") or "").strip().lower()
                if active_stage in _VALID_STREAM_STAGES:
                    return active_stage
            return current_stage
        metadata = event.get("metadata") or {}
        node = ""
        if isinstance(metadata, dict):
            node = str(metadata.get("langgraph_node") or "").strip()
        if not node:
            node = str(event.get("name") or "").strip()
        return _GRAPH_NODE_STAGE.get(node, current_stage)

    def _heartbeat_message(stage: str, *, warning: bool) -> str:
        if warning:
            messages = {
                "planning": "Planning is taking longer than usual, still running.",
                "research": "Research retrieval is taking longer than usual, still running.",
                "synthesis": "Synthesis is taking longer than usual, still running.",
                "evaluation": "Evaluation is taking longer than usual, still running.",
                "finalizing": "Finalization is taking longer than usual, still running.",
            }
            return messages.get(stage, "Pipeline is taking longer than usual, still running.")
        messages = {
            "planning": "Planning execution path and task decomposition...",
            "research": "Research is still collecting and filtering sources...",
            "synthesis": "Synthesis is still generating the report draft...",
            "evaluation": "Evaluation is still validating quality and citations...",
            "finalizing": "Finalizing artifacts and report packaging...",
        }
        return messages.get(stage, "Pipeline is still running...")

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event in events_iterable:
                await queue.put(event)
        finally:
            await queue.put(None)

    producer_task = asyncio.create_task(producer())
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    active_stage = "planning"
    last_real_event_at = started_at
    warned_idle = False
    try:
        while True:
            now = loop.time()
            idle_sec = now - last_real_event_at
            elapsed_sec = now - started_at
            idle_threshold = _threshold(active_stage)
            warn_threshold = max(1, int(idle_threshold * max(0.1, min(0.95, warn_before_idle_ratio))))
            if max_runtime_seconds > 0 and (now - started_at) >= max_runtime_seconds:
                yield {
                    "event": "on_custom_event",
                    "data": {
                        "type": "error",
                        "stage": "error",
                        "active_stage": active_stage,
                        "elapsed_sec": int(elapsed_sec),
                        "idle_sec": int(idle_sec),
                        "idle_threshold_sec": idle_threshold,
                        "warned_idle": warned_idle,
                        "reason_codes": ["max_runtime_exceeded", f"max_runtime_stage_{active_stage}"],
                        "message": (
                            f"Pipeline exceeded max runtime ({max_runtime_seconds}s). "
                            "Run stopped to avoid indefinite hanging. Retry with a narrower query or reduced depth."
                        ),
                    },
                }
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval_seconds)
            except TimeoutError:
                now = loop.time()
                idle_sec = now - last_real_event_at
                elapsed_sec = now - started_at
                idle_threshold = _threshold(active_stage)
                warn_threshold = max(1, int(idle_threshold * max(0.1, min(0.95, warn_before_idle_ratio))))
                if not warned_idle and idle_sec >= warn_threshold:
                    warned_idle = True
                    yield {
                        "event": "on_custom_event",
                        "data": {
                            "type": "status",
                            "stage": active_stage,
                            "active_stage": active_stage,
                            "message": _heartbeat_message(active_stage, warning=True),
                            "elapsed_sec": int(elapsed_sec),
                            "idle_sec": int(idle_sec),
                            "idle_threshold_sec": idle_threshold,
                            "warned_idle": True,
                            "is_heartbeat": True,
                            "reason_codes": [f"idle_warning_stage_{active_stage}"],
                        },
                    }
                if idle_sec >= idle_threshold:
                    yield {
                        "event": "on_custom_event",
                        "data": {
                            "type": "error",
                            "stage": "error",
                            "active_stage": active_stage,
                            "elapsed_sec": int(elapsed_sec),
                            "idle_sec": int(idle_sec),
                            "idle_threshold_sec": idle_threshold,
                            "warned_idle": warned_idle,
                            "reason_codes": ["idle_timeout", f"idle_timeout_stage_{active_stage}"],
                            "message": (
                                f"No pipeline progress for {idle_threshold}s in {active_stage}. "
                                "Run stopped due to idle timeout. Retry and inspect provider health."
                            ),
                        },
                    }
                    break
                yield {
                    "event": "on_custom_event",
                    "data": {
                        "type": "status",
                        "stage": active_stage,
                        "active_stage": active_stage,
                        "message": _heartbeat_message(active_stage, warning=False),
                        "elapsed_sec": int(elapsed_sec),
                        "idle_sec": int(idle_sec),
                        "idle_threshold_sec": idle_threshold,
                        "warned_idle": warned_idle,
                        "is_heartbeat": True,
                    },
                }
                continue

            if item is None:
                break
            new_stage = _resolve_stage_from_event(item, active_stage)
            now = loop.time()
            if new_stage != active_stage:
                active_stage = new_stage
                warned_idle = False
            last_real_event_at = now
            yield item
    finally:
        if not producer_task.done():
            producer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer_task


@app.get("/health")
def health() -> dict[str, object]:
    cfg = load_config({"interactive_hitl": False})
    startup = _startup_diagnostics(cfg)
    return {
        "status": "ok",
        "startup_guard_mode": startup["startup_guard_mode"],
        "startup_reason_codes": startup["startup_reason_codes"],
        "optional_dependency_status": startup["optional_dependency_status"],
    }


@app.get("/health/deps")
def health_deps() -> dict:
    cfg = load_config({"interactive_hitl": False})
    return {"status": "ok", **dependency_health(cfg)}


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.post("/research")
def research(request: ResearchRequest) -> dict:
    overrides = _request_overrides(request)
    config = load_config(overrides)
    startup = _startup_diagnostics(config)
    startup_reason_codes_list = list(startup["startup_reason_codes"])  # type: ignore[arg-type]
    if config.startup_guard_mode == "strict" and startup_reason_codes_list:
        raise HTTPException(
            status_code=503,
            detail=(
                "Startup guard blocked execution due to missing optional dependencies: "
                + ", ".join(startup_reason_codes_list)
            ),
        )
    if request.execution_mode == "distributed" and not config.enable_distributed:
        raise HTTPException(
            status_code=503,
            detail="Distributed execution is disabled by runtime profile/config.",
        )
    use_distributed = _should_use_distributed(
        request.query,
        request.execution_mode,
        distributed_enabled=config.enable_distributed,
        distributed_auto_enabled=config.distributed_auto_enabled,
    )
    fallback_reason: str | None = None
    if use_distributed:
        helpers = _distributed_helpers()
        if helpers is None or not _distributed_available():
            if request.execution_mode == "distributed":
                raise HTTPException(
                    status_code=503,
                    detail="Distributed execution requested but Celery is unavailable.",
                )
            fallback_reason = "Distributed execution unavailable; falling back to inline."
        else:
            ready, reason = helpers["is_ready"](
                timeout_seconds=config.distributed_health_timeout_seconds
            )
            if not ready:
                if request.execution_mode == "distributed":
                    raise HTTPException(
                        status_code=503,
                        detail=f"Distributed execution requested but not ready: {reason}",
                    )
                fallback_reason = (
                    f"Distributed execution unavailable; falling back to inline ({reason})."
                )
            else:
                try:
                    task = helpers["dispatch"](
                        query=request.query,
                        tenant_id=request.tenant_id,
                    )
                    payload = helpers["wait_result"](
                        task,
                        queue_wait_seconds=config.distributed_queue_wait_seconds,
                        result_timeout_seconds=15,
                    )
                    payload["execution_mode_used"] = "distributed"
                    payload["execution_mode_requested"] = request.execution_mode
                    payload["task_id"] = task.id
                    payload["startup_reason_codes"] = startup_reason_codes_list
                    payload["optional_dependency_status"] = startup["optional_dependency_status"]
                    return payload
                except Exception as e:
                    if request.execution_mode == "distributed":
                        raise HTTPException(
                            status_code=503,
                            detail=f"Distributed execution failed: {e}",
                        ) from e
                    fallback_reason = f"Distributed execution failed: {e}"

    result = run_research(request.query, config=config)
    payload = result.model_dump(mode="json")
    payload["execution_mode_used"] = "inline"
    payload["execution_mode_requested"] = request.execution_mode
    payload["startup_reason_codes"] = startup_reason_codes_list
    payload["optional_dependency_status"] = startup["optional_dependency_status"]
    if fallback_reason:
        payload["execution_mode_fallback_reason"] = fallback_reason
    return payload


@app.get("/research/stream")
async def research_stream(
    query: str,
    tenant_id: str = "default",
    execution_mode: Literal["auto", "inline", "distributed"] = "inline",
    mcp_mode: Literal["auto", "inprocess", "transport"] | None = None,
    runtime_profile: Literal["minimal", "balanced", "full"] | None = None,
    startup_guard_mode: Literal["hybrid", "strict"] | None = None,
    subtopic_mode: Literal["disabled", "map_reduce"] | None = None,
    subtopic_count_default: int | None = None,
    subtopic_count_max: int | None = None,
    subreport_failure_policy: Literal["continue_constrained", "retry_once", "fail_closed"] | None = None,
    report_completion_mode: Literal["strict_no_placeholders", "template_fill"] | None = None,
    tier_policy_mode: Literal["primary_only_strict", "hybrid_strict", "broad"] | None = None,
    report_structure_mode: Literal["decision_brief", "academic_17"] | None = None,
    availability_enforcement_scope: Literal["intent_triggered", "always", "never"] | None = None,
    opportunity_query_detection: Literal["auto", "strict", "off"] | None = None,
    report_surface_mode: Literal["decision_brief_only", "brief_plus_confidence", "full_technical"] | None = None,
    top_section_min_verified_claims: int | None = None,
    insight_density_min: int | None = None,
    report_voice_mode: Literal["analyst", "neutral"] | None = None,
    min_primary_verified_findings: int | None = None,
) -> StreamingResponse:
    # 1. Config & Runtime
    overrides = {
        "tenant_id": tenant_id,
        "interactive_hitl": False,  # Stream cannot handle interactive yet
    }
    if mcp_mode is not None:
        overrides["mcp_mode"] = mcp_mode
    if runtime_profile is not None:
        overrides["runtime_profile"] = runtime_profile
    if startup_guard_mode is not None:
        overrides["startup_guard_mode"] = startup_guard_mode
    if subtopic_mode is not None:
        overrides["subtopic_mode"] = subtopic_mode
    if subtopic_count_default is not None:
        overrides["subtopic_count_default"] = subtopic_count_default
    if subtopic_count_max is not None:
        overrides["subtopic_count_max"] = subtopic_count_max
    if subreport_failure_policy is not None:
        overrides["subreport_failure_policy"] = subreport_failure_policy
    if report_completion_mode is not None:
        overrides["report_completion_mode"] = report_completion_mode
    if tier_policy_mode is not None:
        overrides["tier_policy_mode"] = tier_policy_mode
    if report_structure_mode is not None:
        overrides["report_structure_mode"] = report_structure_mode
    if availability_enforcement_scope is not None:
        overrides["availability_enforcement_scope"] = availability_enforcement_scope
    if opportunity_query_detection is not None:
        overrides["opportunity_query_detection"] = opportunity_query_detection
    if report_surface_mode is not None:
        overrides["report_surface_mode"] = report_surface_mode
    if top_section_min_verified_claims is not None:
        overrides["top_section_min_verified_claims"] = top_section_min_verified_claims
    if insight_density_min is not None:
        overrides["insight_density_min"] = insight_density_min
    if report_voice_mode is not None:
        overrides["report_voice_mode"] = report_voice_mode
    if min_primary_verified_findings is not None:
        overrides["min_primary_verified_findings"] = min_primary_verified_findings
    config = load_config(overrides)
    startup = _startup_diagnostics(config)

    # 2. Generator Wrapper
    async def stream_wrapper():
        # Yield start event
        yield f"data: {json.dumps({'type': 'status', 'stage': 'starting', 'active_stage': 'planning', 'query': query})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'stage': 'accepted', 'active_stage': 'planning', 'message': 'Request accepted. Building research plan.'})}\n\n"
        use_distributed = _should_use_distributed(
            query,
            execution_mode,
            distributed_enabled=config.enable_distributed,
            distributed_auto_enabled=config.distributed_auto_enabled,
        )
        yield f"data: {json.dumps({'type': 'status', 'stage': 'planning', 'active_stage': 'planning', 'message': 'Pipeline initialized. Preparing execution strategy.'})}\n\n"
        reason_codes = list(startup["startup_reason_codes"])  # type: ignore[arg-type]
        if reason_codes:
            startup_msg = (
                "Startup diagnostics detected optional dependency limits. Running with safe fallback behavior."
            )
            startup_payload = {
                "type": "status",
                "stage": "planning",
                "active_stage": "planning",
                "message": startup_msg,
                "reason_codes": reason_codes,
                "optional_dependency_status": startup["optional_dependency_status"],
            }
            yield f"data: {json.dumps(startup_payload)}\n\n"
            if config.startup_guard_mode == "strict":
                err_payload = {
                    "type": "error",
                    "message": "Startup guard is strict and blocked this run due to dependency diagnostics.",
                    "reason_codes": reason_codes,
                }
                yield f"data: {json.dumps(err_payload)}\n\n"
                return

        if execution_mode == "distributed" and not config.enable_distributed:
            err_payload = {
                "type": "error",
                "message": "Distributed execution is disabled by runtime profile/config.",
            }
            yield f"data: {json.dumps(err_payload)}\n\n"
            return

        if execution_mode == "auto" and not config.enable_distributed:
            warn_payload = {
                "type": "status",
                "stage": "fallback",
                "active_stage": "planning",
                "message": "Distributed mode disabled by profile; running inline.",
            }
            yield f"data: {json.dumps(warn_payload)}\n\n"

        if use_distributed:
            helpers = _distributed_helpers()
            if helpers is None or not _distributed_available():
                if execution_mode == "distributed":
                    err_payload = {
                        "type": "error",
                        "message": "Distributed execution requested but Celery is unavailable.",
                    }
                    yield f"data: {json.dumps(err_payload)}\n\n"
                    return
                warn_payload = {
                    "type": "status",
                    "stage": "fallback",
                    "active_stage": "planning",
                    "message": "Distributed mode unavailable; running inline.",
                }
                yield f"data: {json.dumps(warn_payload)}\n\n"
            else:
                ready, reason = await asyncio.to_thread(
                    helpers["is_ready"],
                    timeout_seconds=config.distributed_health_timeout_seconds,
                )
                if not ready:
                    if execution_mode == "distributed":
                        err_payload = {
                            "type": "error",
                            "message": f"Distributed execution requested but not ready: {reason}",
                        }
                        yield f"data: {json.dumps(err_payload)}\n\n"
                        return
                    warn_payload = {
                        "type": "status",
                        "stage": "fallback",
                        "message": f"Distributed mode unavailable; running inline ({reason}).",
                    }
                    yield f"data: {json.dumps(warn_payload)}\n\n"
                else:
                    try:
                        task = await asyncio.to_thread(
                            helpers["dispatch"],
                            query=query,
                            tenant_id=tenant_id,
                        )
                        queued_payload = {
                        "type": "status",
                        "stage": "queued",
                        "active_stage": "planning",
                        "message": "Query queued for distributed processing.",
                        "task_id": task.id,
                    }
                        yield f"data: {json.dumps(queued_payload)}\n\n"
                        deadline = asyncio.get_running_loop().time() + max(
                            1, config.distributed_queue_wait_seconds
                        )
                        while True:
                            is_ready = await asyncio.to_thread(task.ready)
                            if is_ready:
                                result = await asyncio.to_thread(task.get, timeout=10)
                                final_payload = {
                                    "type": "status",
                                    "stage": "final",
                                    "data": {
                                        "result": {
                                            "run_id": result.get("run_id"),
                                            "status": result.get("status", "completed"),
                                            "final_report": result.get("final_report", ""),
                                            "artifacts_path": result.get("artifacts_path", ""),
                                        }
                                    },
                                }
                                yield f"data: {json.dumps(final_payload)}\n\n"
                                done_payload = {"type": "done", "final_emitted": True}
                                yield f"data: {json.dumps(done_payload)}\n\n"
                                return
                            if asyncio.get_running_loop().time() >= deadline:
                                raise TimeoutError(
                                    f"Distributed queue wait exceeded {config.distributed_queue_wait_seconds}s."
                                )
                            running_payload = {
                                "type": "status",
                                "stage": "research",
                                "active_stage": "research",
                                "message": "Distributed worker processing query...",
                                "task_id": task.id,
                            }
                            yield f"data: {json.dumps(running_payload)}\n\n"
                            await asyncio.sleep(1.0)
                    except Exception as e:
                        if execution_mode == "distributed":
                            err_payload = {
                                "type": "error",
                                "message": f"Distributed execution failed: {e}",
                            }
                            yield f"data: {json.dumps(err_payload)}\n\n"
                            return
                        warn_payload = {
                            "type": "status",
                            "stage": "fallback",
                            "message": f"Distributed mode unavailable; falling back to inline stream ({e}).",
                        }
                        yield f"data: {json.dumps(warn_payload)}\n\n"

        try:
            # We must manage the runtime lifecycle within the generator
            with GraphRuntime.from_config(config) as runtime:
                graph = build_graph(runtime)
                initial_state = build_initial_state(query, runtime)
                yield f"data: {json.dumps({'type': 'status', 'stage': 'research', 'active_stage': 'research', 'message': 'Retrieving evidence across sources.'})}\n\n"

                # Stream events from LangGraph
                # version="v2" is required for astream_events in newer langgraph
                events = _with_heartbeat(
                    graph.astream_events(initial_state, version="v2"),
                    interval_seconds=2.5,
                    max_runtime_seconds=config.stream_max_runtime_seconds,
                    warn_before_idle_ratio=config.stream_warn_before_idle_ratio,
                    stage_idle_seconds={
                        "planning": config.stream_stage_idle_seconds_planning,
                        "research": config.stream_stage_idle_seconds_research,
                        "synthesis": config.stream_stage_idle_seconds_synthesis,
                        "evaluation": config.stream_stage_idle_seconds_evaluation,
                        "finalizing": config.stream_stage_idle_seconds_finalizing,
                    },
                )
                async for sse_chunk in event_generator(events):
                    yield sse_chunk

        except Exception as e:
            # Yield error event
            err_payload = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err_payload)}\n\n"
    return StreamingResponse(
        stream_wrapper(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def main() -> None:
    import uvicorn

    uvicorn.run("service.api:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
