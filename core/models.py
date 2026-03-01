from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class TaskSpec(BaseModel):
    id: int
    title: str
    search_query: str
    tool_hint: Literal["tavily", "ddg", "firecrawl", "any"] = "any"
    priority: int = 1
    firecrawl_needed: bool = False


class SubTopic(BaseModel):
    id: str
    facet: str
    sub_query: str
    rationale: str = ""
    complexity: Literal["low", "medium", "high"] = "medium"


class RetrievedDoc(BaseModel):
    provider: Literal["tavily", "ddg", "firecrawl", "memory", "fallback"]
    title: str
    url: str = ""
    snippet: str = ""
    content: str = ""
    score: float = 0.0
    retrieved_at: str = Field(default_factory=utc_now_iso)
    meta: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    claim_id: str
    source_url: str
    title: str = ""
    provider: str = ""
    evidence: str = ""
    source_tier: Literal["A", "B", "C", "unknown"] = "unknown"
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"


class ClaimRecord(BaseModel):
    claim_id: str
    assertion: str
    status: Literal["verified", "constrained", "withheld"] = "constrained"
    reason_codes: list[str] = Field(default_factory=list)
    evidence: str = ""


class EvalResult(BaseModel):
    faithfulness: float = 0.0
    relevancy: float = 0.0
    citation_coverage: float = 0.0
    pass_gate: bool = False
    reasons: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class SubReport(BaseModel):
    sub_query: str
    facet: str
    content: str
    claims: list[ClaimRecord] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: Literal["high", "mixed", "constrained"] = "constrained"
    reason_codes: list[str] = Field(default_factory=list)
    missing_proof_fields: list[str] = Field(default_factory=list)


class QueryProfile(BaseModel):
    intent_type: Literal[
        "explanatory",
        "comparative",
        "operational",
        "security_dual_use",
        "diagnostic",
    ] = "explanatory"
    domain_facets: list[str] = Field(default_factory=list)
    risk_band: Literal["low", "medium", "high"] = "low"
    dual_use: bool = False
    original_query: str = ""
    normalized_query: str = ""
    typed_constraints: dict[str, str] = Field(default_factory=dict)
    must_have_evidence_fields: list[str] = Field(default_factory=list)


class TenantContext(BaseModel):
    tenant_id: str = "default"
    org_id: str = "default-org"
    user_id: str = "default-user"
    quota_tier: Literal["free", "pro", "enterprise"] = "free"
    rate_limits: dict[str, int] = Field(
        default_factory=lambda: {"queries_per_hour": 60, "tokens_per_day": 200_000}
    )


class ResearchUpdate(BaseModel):
    stage: Literal["accepted", "planning", "research", "synthesis", "evaluation", "final", "error"]
    data: dict[str, Any] = Field(default_factory=dict)


class RunConfig(BaseModel):
    runtime_profile: Literal["minimal", "balanced", "full"] = "minimal"
    startup_guard_mode: Literal["hybrid", "strict"] = "hybrid"
    enable_distributed: bool = False
    enable_observability: bool = False
    enable_storage: bool = False
    subtopic_mode: Literal["disabled", "map_reduce"] = "map_reduce"
    subtopic_count_default: int = 3
    subtopic_count_max: int = 4
    subreport_target_words: int = 450
    subreport_min_claims: int = 3
    subreport_gapfill_enabled: bool = True
    subreport_gapfill_max_queries: int = 2
    subreport_failure_policy: Literal["continue_constrained", "retry_once", "fail_closed"] = "continue_constrained"
    research_mode: Literal["fast", "balanced", "peak"] = "peak"
    fact_mode: Literal["strict", "balanced", "open_web"] = "strict"
    crawl_strategy: Literal["wide_then_filter", "dual_lane", "aggressive"] = "wide_then_filter"
    availability_policy: Literal["must_be_open", "recent_or_open", "unknown_allowed"] = "must_be_open"
    freshness_max_months: int = 12
    verification_min_sources_per_claim: int = 2
    require_primary_or_official_proof: bool = True
    verified_findings_min: int = 8
    report_artifact_mode: Literal["narrative_plus_register", "narrative_only", "register_only"] = "narrative_plus_register"
    report_completion_mode: Literal["strict_no_placeholders", "template_fill"] = "strict_no_placeholders"
    tier_policy_mode: Literal["primary_only_strict", "hybrid_strict", "broad"] = "primary_only_strict"
    report_structure_mode: Literal["decision_brief", "academic_17"] = "academic_17"
    availability_enforcement_scope: Literal["intent_triggered", "always", "never"] = "intent_triggered"
    opportunity_query_detection: Literal["auto", "strict", "off"] = "auto"
    report_surface_mode: Literal["decision_brief_only", "brief_plus_confidence", "full_technical"] = "decision_brief_only"
    top_section_min_verified_claims: int = 3
    top_section_max_ctier_ratio: float = 0.20
    insight_density_min: int = 8
    mechanics_ratio_max_top_sections: float = 0.018
    constrained_brief_min_specific_actions: int = 3
    report_voice_mode: Literal["analyst", "neutral"] = "analyst"
    require_verified_findings_in_direct_answer: bool = True
    min_primary_verified_findings: int = 5
    allow_placeholder_sections: bool = False
    primary_domain_allowlist_mode: Literal["explicit", "heuristic"] = "explicit"
    primary_source_policy: Literal["strict", "hybrid", "broad"] = "strict"
    max_planner_tasks_peak: int = 8
    min_primary_claims: int = 8
    min_ab_sources: int = 6
    min_unique_domains: int = 6
    max_ctier_claim_ratio: float = 0.30
    auto_retry_for_quality: bool = True
    auto_retry_quality_passes: int = 1
    contradiction_scan_required: bool = True
    target_report_words_peak_min: int = 2500
    target_report_words_peak_max: int = 3800
    show_technical_sections_default: bool = False
    groq_model: str = "llama-3.1-8b-instant"
    judge_provider: Literal["groq", "hf", "stub"] = "groq"
    judge_json_mode: Literal["repair_retry_fallback", "strict", "heuristic"] = "repair_retry_fallback"
    research_depth: Literal["fast", "balanced", "deep"] = "deep"
    source_policy: Literal["external_only", "external_preferred", "mixed"] = "external_only"
    no_source_mode: Literal["fail_closed", "warn_partial", "memory_backup"] = "fail_closed"
    report_style: Literal["brief_appendix", "full_narrative", "decision_dashboard"] = "brief_appendix"
    report_presentation: Literal["book", "standard"] = "book"
    sources_presentation: Literal["cards_with_ledger", "ledger_only"] = "cards_with_ledger"
    show_raw_source_ledger_default: bool = False
    method_narrative_enabled: bool = True
    strict_high_confidence: bool = True
    truth_mode: Literal["strict", "balanced", "always_answer"] = "balanced"
    claim_policy: Literal["adaptive_scoring", "tier_first", "coverage_first"] = "adaptive_scoring"
    evidence_floor_mode: Literal["adaptive", "fixed_high", "fixed_medium"] = "adaptive"
    insufficient_evidence_output: Literal["constrained_actionable", "fail_closed", "soft_fallback"] = "constrained_actionable"
    query_cleanup_mode: Literal["aggressive", "light", "none"] = "aggressive"
    narrative_citation_density: Literal["light_inline", "dense_inline", "footnote"] = "light_inline"
    min_claim_confidence_to_assert: float = 0.62
    max_unverified_claim_ratio: float = 0.20
    require_contradiction_scan: bool = True
    max_sources_snapshot: int = 6
    source_quality_bar: Literal["high_confidence", "mixed", "broad"] = "high_confidence"
    dual_use_depth: Literal["dynamic_defensive", "dynamic_balanced", "dynamic_strict"] = "dynamic_defensive"
    min_external_sources: int = 5
    min_unique_providers: int = 2
    min_tier_ab_sources: int = 2
    max_evidence_quote_chars: int = 180
    require_corroboration_for_tier_c: bool = True
    min_report_words_deep: int = 2200
    min_claims_deep: int = 10
    max_tasks: int = 3
    max_retries: int = 3
    correction_loop_limit: int = 1
    faithfulness_threshold: float = 0.70
    relevancy_threshold: float = 0.70
    citation_threshold: float = 0.85
    groq_rpm: int = 20
    tavily_rpm: int = 5
    ddg_rpm: int = 20
    firecrawl_rpm: int = 3
    judge_rpm: int = 15
    per_doc_tokens: int = 500
    total_context_tokens: int = 1800
    output_dir: str = "outputs"
    logs_dir: str = "logs"
    data_dir: str = "data"
    memory_dir: str = "data/chroma"
    retention_days: int = 30
    hitl_mode: Literal["on_low_confidence", "always", "never"] = "on_low_confidence"
    interactive_hitl: bool = True
    groq_api_key: str | None = None
    tavily_api_key: str | None = None
    firecrawl_api_key: str | None = None
    hf_token: str | None = None
    langsmith_api_key: str | None = None
    langsmith_workspace_id: str | None = None
    deepeval_telemetry: str = "off"
    mcp_mode: Literal["transport", "inprocess", "auto"] = "auto"
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_web_server_cmd: str = "python -m mcp_server.web_stdio_app"
    mcp_local_server_cmd: str = "python -m mcp_server.local_stdio_app"
    mcp_web_http_server_cmd: str = "python -m mcp_server.web_streamable_http_app"
    mcp_local_http_server_cmd: str = "python -m mcp_server.local_streamable_http_app"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port_web: int = 8001
    mcp_http_port_local: int = 8002
    mcp_http_web_url: str | None = None
    mcp_http_local_url: str | None = None
    mcp_http_external: bool = False
    mcp_auth_token: str | None = None
    mcp_client_auth_token: str | None = None
    mcp_allow_insecure_http: bool = False
    mcp_allow_external_bind: bool = False
    mcp_startup_timeout_seconds: int = 20
    mcp_call_timeout_seconds: int = 15
    metrics_enabled: bool = False
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9010
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    database_url: str | None = None
    expected_github_owner: str = "UbaidZafar"
    tenant_id: str = "default"
    tenant_org_id: str = "default-org"
    tenant_user_id: str = "default-user"
    tenant_quota_tier: Literal["free", "pro", "enterprise"] = "free"
    tenant_queries_per_hour: int = 60
    tenant_tokens_per_day: int = 200_000
    model_routing_strategy: Literal["adaptive", "cost_optimized", "latency_optimized"] = "adaptive"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    huggingface_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    openrouter_model: str = "openrouter/free"
    # Task-specific overrides (Provider:Model)
    planner_model: str | None = None
    researcher_model: str | None = None
    synthesizer_model: str | None = None
    evaluator_model: str | None = None
    preferred_free_provider: Literal["groq", "huggingface", "openrouter"] = "groq"
    enable_local_llm: bool = False
    local_llm_endpoint: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    distributed_health_timeout_seconds: int = 2
    distributed_queue_wait_seconds: int = 90
    distributed_auto_enabled: bool = True
    stream_stage_idle_seconds_planning: int = 120
    stream_stage_idle_seconds_research: int = 180
    stream_stage_idle_seconds_synthesis: int = 420
    stream_stage_idle_seconds_evaluation: int = 180
    stream_stage_idle_seconds_finalizing: int = 180
    stream_max_runtime_seconds: int = 900
    stream_warn_before_idle_ratio: float = 0.70
    llm_request_timeout_seconds_research: int = 90
    llm_request_timeout_seconds_synthesis: int = 240
    llm_request_timeout_seconds_correction: int = 180
    ddg_text_enabled: bool = True
    ddg_fallback_mode: Literal["instant_only", "provider_shift", "mixed"] = "provider_shift"
    ddg_suppress_impersonate_warnings: bool = True
    stream_max_idle_seconds: int = 120
    quota_pressure_mode: bool = False


class ResearchResult(BaseModel):
    run_id: str
    query: str
    final_report: str
    citations: list[Citation] = Field(default_factory=list)
    eval_result: EvalResult
    low_confidence: bool = False
    status: str = "completed"
    artifacts_path: str = ""
    tenant_id: str = "default"
    report_meta: dict[str, Any] = Field(default_factory=dict)
