from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.models import RunConfig
from core.runtime_profile import derive_profile_flags


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _env_optional_bool(key: str) -> bool | None:
    value = os.getenv(key)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_dirs(config: RunConfig) -> None:
    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
    Path(config.logs_dir).mkdir(parents=True, exist_ok=True)
    Path(config.data_dir).mkdir(parents=True, exist_ok=True)
    Path(config.memory_dir).mkdir(parents=True, exist_ok=True)


def load_config(overrides: dict[str, Any] | None = None) -> RunConfig:
    load_dotenv(override=False)
    overrides = overrides or {}
    runtime_profile = str(overrides.get("runtime_profile") or os.getenv("RUNTIME_PROFILE", "minimal"))
    enable_distributed_override = (
        bool(overrides["enable_distributed"])
        if "enable_distributed" in overrides
        else _env_optional_bool("ENABLE_DISTRIBUTED")
    )
    enable_observability_override = (
        bool(overrides["enable_observability"])
        if "enable_observability" in overrides
        else _env_optional_bool("ENABLE_OBSERVABILITY")
    )
    enable_storage_override = (
        bool(overrides["enable_storage"])
        if "enable_storage" in overrides
        else _env_optional_bool("ENABLE_STORAGE")
    )
    profile_flags = derive_profile_flags(
        runtime_profile,
        enable_distributed=enable_distributed_override,
        enable_observability=enable_observability_override,
        enable_storage=enable_storage_override,
    )
    data: dict[str, Any] = {
        "runtime_profile": runtime_profile,
        "startup_guard_mode": os.getenv("STARTUP_GUARD_MODE", "hybrid"),
        "enable_distributed": profile_flags["enable_distributed"],
        "enable_observability": profile_flags["enable_observability"],
        "enable_storage": profile_flags["enable_storage"],
        "subtopic_mode": os.getenv("SUBTOPIC_MODE", "map_reduce"),
        "subtopic_count_default": _env_int("SUBTOPIC_COUNT_DEFAULT", 3),
        "subtopic_count_max": _env_int("SUBTOPIC_COUNT_MAX", 4),
        "subreport_target_words": _env_int("SUBREPORT_TARGET_WORDS", 450),
        "subreport_min_claims": _env_int("SUBREPORT_MIN_CLAIMS", 3),
        "subreport_gapfill_enabled": _env_bool("SUBREPORT_GAPFILL_ENABLED", True),
        "subreport_gapfill_max_queries": _env_int("SUBREPORT_GAPFILL_MAX_QUERIES", 2),
        "subreport_failure_policy": os.getenv("SUBREPORT_FAILURE_POLICY", "continue_constrained"),
        "research_mode": os.getenv("RESEARCH_MODE", "peak"),
        "fact_mode": os.getenv("FACT_MODE", "strict"),
        "crawl_strategy": os.getenv("CRAWL_STRATEGY", "wide_then_filter"),
        "availability_policy": os.getenv("AVAILABILITY_POLICY", "must_be_open"),
        "freshness_max_months": _env_int("FRESHNESS_MAX_MONTHS", 12),
        "verification_min_sources_per_claim": _env_int("VERIFICATION_MIN_SOURCES_PER_CLAIM", 2),
        "require_primary_or_official_proof": _env_bool("REQUIRE_PRIMARY_OR_OFFICIAL_PROOF", True),
        "verified_findings_min": _env_int("VERIFIED_FINDINGS_MIN", 8),
        "report_artifact_mode": os.getenv("REPORT_ARTIFACT_MODE", "narrative_plus_register"),
        "report_completion_mode": os.getenv("REPORT_COMPLETION_MODE", "strict_no_placeholders"),
        "tier_policy_mode": os.getenv("TIER_POLICY_MODE", "primary_only_strict"),
        "report_structure_mode": os.getenv("REPORT_STRUCTURE_MODE", "academic_17"),
        "availability_enforcement_scope": os.getenv("AVAILABILITY_ENFORCEMENT_SCOPE", "intent_triggered"),
        "opportunity_query_detection": os.getenv("OPPORTUNITY_QUERY_DETECTION", "auto"),
        "report_surface_mode": os.getenv("REPORT_SURFACE_MODE", "decision_brief_only"),
        "top_section_min_verified_claims": _env_int("TOP_SECTION_MIN_VERIFIED_CLAIMS", 3),
        "top_section_max_ctier_ratio": _env_float("TOP_SECTION_MAX_CTIER_RATIO", 0.20),
        "insight_density_min": _env_int("INSIGHT_DENSITY_MIN", 8),
        "mechanics_ratio_max_top_sections": _env_float("MECHANICS_RATIO_MAX_TOP_SECTIONS", 0.018),
        "constrained_brief_min_specific_actions": _env_int("CONSTRAINED_BRIEF_MIN_SPECIFIC_ACTIONS", 3),
        "report_voice_mode": os.getenv("REPORT_VOICE_MODE", "analyst"),
        "require_verified_findings_in_direct_answer": _env_bool(
            "REQUIRE_VERIFIED_FINDINGS_IN_DIRECT_ANSWER",
            True,
        ),
        "min_primary_verified_findings": _env_int("MIN_PRIMARY_VERIFIED_FINDINGS", 5),
        "allow_placeholder_sections": _env_bool("ALLOW_PLACEHOLDER_SECTIONS", False),
        "primary_domain_allowlist_mode": os.getenv("PRIMARY_DOMAIN_ALLOWLIST_MODE", "explicit"),
        "primary_source_policy": os.getenv("PRIMARY_SOURCE_POLICY", "strict"),
        "max_planner_tasks_peak": _env_int("MAX_PLANNER_TASKS_PEAK", 8),
        "min_primary_claims": _env_int("MIN_PRIMARY_CLAIMS", 8),
        "min_ab_sources": _env_int("MIN_AB_SOURCES", 6),
        "min_unique_domains": _env_int("MIN_UNIQUE_DOMAINS", 6),
        "max_ctier_claim_ratio": _env_float("MAX_CTIER_CLAIM_RATIO", 0.30),
        "auto_retry_for_quality": _env_bool("AUTO_RETRY_FOR_QUALITY", True),
        "auto_retry_quality_passes": _env_int("AUTO_RETRY_QUALITY_PASSES", 1),
        "contradiction_scan_required": _env_bool("CONTRADICTION_SCAN_REQUIRED", True),
        "target_report_words_peak_min": _env_int("TARGET_REPORT_WORDS_PEAK_MIN", 2500),
        "target_report_words_peak_max": _env_int("TARGET_REPORT_WORDS_PEAK_MAX", 3800),
        "show_technical_sections_default": _env_bool("SHOW_TECHNICAL_SECTIONS_DEFAULT", False),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "judge_provider": os.getenv("JUDGE_PROVIDER", "groq"),
        "judge_json_mode": os.getenv("JUDGE_JSON_MODE", "repair_retry_fallback"),
        "research_depth": os.getenv("RESEARCH_DEPTH", "deep"),
        "source_policy": os.getenv("SOURCE_POLICY", "external_only"),
        "no_source_mode": os.getenv("NO_SOURCE_MODE", "fail_closed"),
        "report_style": os.getenv("REPORT_STYLE", "brief_appendix"),
        "report_presentation": os.getenv("REPORT_PRESENTATION", "book"),
        "sources_presentation": os.getenv("SOURCES_PRESENTATION", "cards_with_ledger"),
        "show_raw_source_ledger_default": _env_bool("SHOW_RAW_SOURCE_LEDGER_DEFAULT", False),
        "method_narrative_enabled": _env_bool("METHOD_NARRATIVE_ENABLED", True),
        "strict_high_confidence": _env_bool("STRICT_HIGH_CONFIDENCE", True),
        "truth_mode": os.getenv("TRUTH_MODE", "balanced"),
        "claim_policy": os.getenv("CLAIM_POLICY", "adaptive_scoring"),
        "evidence_floor_mode": os.getenv("EVIDENCE_FLOOR_MODE", "adaptive"),
        "insufficient_evidence_output": os.getenv("INSUFFICIENT_EVIDENCE_OUTPUT", "constrained_actionable"),
        "query_cleanup_mode": os.getenv("QUERY_CLEANUP_MODE", "aggressive"),
        "narrative_citation_density": os.getenv("NARRATIVE_CITATION_DENSITY", "light_inline"),
        "min_claim_confidence_to_assert": _env_float("MIN_CLAIM_CONFIDENCE_TO_ASSERT", 0.62),
        "max_unverified_claim_ratio": _env_float("MAX_UNVERIFIED_CLAIM_RATIO", 0.20),
        "require_contradiction_scan": _env_bool("REQUIRE_CONTRADICTION_SCAN", True),
        "max_sources_snapshot": _env_int("MAX_SOURCES_SNAPSHOT", 6),
        "source_quality_bar": os.getenv("SOURCE_QUALITY_BAR", "high_confidence"),
        "dual_use_depth": os.getenv("DUAL_USE_DEPTH", "dynamic_defensive"),
        "min_external_sources": _env_int("MIN_EXTERNAL_SOURCES", 5),
        "min_unique_providers": _env_int("MIN_UNIQUE_PROVIDERS", 2),
        "min_tier_ab_sources": _env_int("MIN_TIER_AB_SOURCES", 2),
        "max_evidence_quote_chars": _env_int("MAX_EVIDENCE_QUOTE_CHARS", 180),
        "require_corroboration_for_tier_c": _env_bool("REQUIRE_CORROBORATION_FOR_TIER_C", True),
        "min_report_words_deep": _env_int("MIN_REPORT_WORDS_DEEP", 2200),
        "min_claims_deep": _env_int("MIN_CLAIMS_DEEP", 10),
        "max_tasks": _env_int("MAX_TASKS", 3),
        "max_retries": _env_int("MAX_RETRIES", 3),
        "correction_loop_limit": _env_int("CORRECTION_LOOP_LIMIT", 1),
        "faithfulness_threshold": _env_float("FAITHFULNESS_THRESHOLD", 0.70),
        "relevancy_threshold": _env_float("RELEVANCY_THRESHOLD", 0.70),
        "citation_threshold": _env_float("CITATION_THRESHOLD", 0.85),
        "groq_rpm": _env_int("GROQ_RPM", 20),
        "tavily_rpm": _env_int("TAVILY_RPM", 5),
        "ddg_rpm": _env_int("DDG_RPM", 20),
        "firecrawl_rpm": _env_int("FIRECRAWL_RPM", 3),
        "judge_rpm": _env_int("JUDGE_RPM", 15),
        "per_doc_tokens": _env_int("PER_DOC_TOKENS", 500),
        "total_context_tokens": _env_int("TOTAL_CONTEXT_TOKENS", 1800),
        "output_dir": os.getenv("OUTPUT_DIR", "outputs"),
        "logs_dir": os.getenv("LOGS_DIR", "logs"),
        "data_dir": os.getenv("DATA_DIR", "data"),
        "memory_dir": os.getenv("MEMORY_DIR", "data/chroma"),
        "retention_days": _env_int("RETENTION_DAYS", 30),
        "hitl_mode": os.getenv("HITL_MODE", "on_low_confidence"),
        "interactive_hitl": _env_bool("INTERACTIVE_HITL", True),
        "groq_api_key": os.getenv("GROQ_API_KEY"),
        "tavily_api_key": os.getenv("TAVILY_API_KEY"),
        "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY"),
        "hf_token": os.getenv("HF_TOKEN"),
        "langsmith_api_key": os.getenv("LANGSMITH_API_KEY"),
        "langsmith_workspace_id": os.getenv("LANGSMITH_WORKSPACE_ID"),
        "deepeval_telemetry": os.getenv("DEEPEVAL_TELEMETRY", "off"),
        "mcp_mode": os.getenv("MCP_MODE", "auto"),
        "mcp_transport": os.getenv("MCP_TRANSPORT", "stdio"),
        "mcp_web_server_cmd": os.getenv(
            "MCP_WEB_SERVER_CMD", "python -m mcp_server.web_stdio_app"
        ),
        "mcp_local_server_cmd": os.getenv(
            "MCP_LOCAL_SERVER_CMD", "python -m mcp_server.local_stdio_app"
        ),
        "mcp_web_http_server_cmd": os.getenv(
            "MCP_WEB_HTTP_SERVER_CMD", "python -m mcp_server.web_streamable_http_app"
        ),
        "mcp_local_http_server_cmd": os.getenv(
            "MCP_LOCAL_HTTP_SERVER_CMD", "python -m mcp_server.local_streamable_http_app"
        ),
        "mcp_http_host": os.getenv("MCP_HTTP_HOST", "127.0.0.1"),
        "mcp_http_port_web": _env_int("MCP_HTTP_PORT_WEB", 8001),
        "mcp_http_port_local": _env_int("MCP_HTTP_PORT_LOCAL", 8002),
        "mcp_http_web_url": os.getenv("MCP_HTTP_WEB_URL"),
        "mcp_http_local_url": os.getenv("MCP_HTTP_LOCAL_URL"),
        "mcp_http_external": _env_bool("MCP_HTTP_EXTERNAL", False),
        "mcp_auth_token": os.getenv("MCP_AUTH_TOKEN"),
        "mcp_client_auth_token": os.getenv("MCP_CLIENT_AUTH_TOKEN"),
        "mcp_allow_insecure_http": _env_bool("MCP_ALLOW_INSECURE_HTTP", False),
        "mcp_allow_external_bind": _env_bool("MCP_ALLOW_EXTERNAL_BIND", False),
        "mcp_startup_timeout_seconds": _env_int("MCP_STARTUP_TIMEOUT_SECONDS", 20),
        "mcp_call_timeout_seconds": _env_int("MCP_CALL_TIMEOUT_SECONDS", 15),
        "metrics_enabled": _env_bool("METRICS_ENABLED", False),
        "metrics_host": os.getenv("METRICS_HOST", "127.0.0.1"),
        "metrics_port": _env_int("METRICS_PORT", 9010),
        "expected_github_owner": os.getenv("EXPECTED_GITHUB_OWNER", "UbaidZafar"),
        "tenant_id": os.getenv("TENANT_ID", "default"),
        "tenant_org_id": os.getenv("TENANT_ORG_ID", "default-org"),
        "tenant_user_id": os.getenv("TENANT_USER_ID", "default-user"),
        "tenant_quota_tier": os.getenv("TENANT_QUOTA_TIER", "free"),
        "tenant_queries_per_hour": _env_int("TENANT_QUERIES_PER_HOUR", 60),
        "tenant_tokens_per_day": _env_int("TENANT_TOKENS_PER_DAY", 200_000),
        "model_routing_strategy": os.getenv("MODEL_ROUTING_STRATEGY", "adaptive"),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
        "huggingface_model": os.getenv("HUGGINGFACE_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        "planner_model": os.getenv("PLANNER_MODEL"),
        "researcher_model": os.getenv("RESEARCHER_MODEL"),
        "synthesizer_model": os.getenv("SYNTHESIZER_MODEL"),
        "evaluator_model": os.getenv("EVALUATOR_MODEL"),
        "preferred_free_provider": os.getenv("PREFERRED_FREE_PROVIDER", "groq"),
        "enable_local_llm": _env_bool("ENABLE_LOCAL_LLM", False),
        "local_llm_endpoint": os.getenv("LOCAL_LLM_ENDPOINT"),
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "celery_broker_url": os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        "celery_result_backend": os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        "distributed_health_timeout_seconds": _env_int("DISTRIBUTED_HEALTH_TIMEOUT_SECONDS", 2),
        "distributed_queue_wait_seconds": _env_int("DISTRIBUTED_QUEUE_WAIT_SECONDS", 90),
        "distributed_auto_enabled": _env_bool(
            "DISTRIBUTED_AUTO_ENABLED",
            profile_flags["enable_distributed"],
        ),
        "stream_stage_idle_seconds_planning": _env_int("STREAM_STAGE_IDLE_SECONDS_PLANNING", 120),
        "stream_stage_idle_seconds_research": _env_int("STREAM_STAGE_IDLE_SECONDS_RESEARCH", 180),
        "stream_stage_idle_seconds_synthesis": _env_int("STREAM_STAGE_IDLE_SECONDS_SYNTHESIS", 420),
        "stream_stage_idle_seconds_evaluation": _env_int("STREAM_STAGE_IDLE_SECONDS_EVALUATION", 180),
        "stream_stage_idle_seconds_finalizing": _env_int("STREAM_STAGE_IDLE_SECONDS_FINALIZING", 180),
        "stream_max_runtime_seconds": _env_int("STREAM_MAX_RUNTIME_SECONDS", 900),
        "stream_warn_before_idle_ratio": _env_float("STREAM_WARN_BEFORE_IDLE_RATIO", 0.70),
        "llm_request_timeout_seconds_research": _env_int("LLM_REQUEST_TIMEOUT_SECONDS_RESEARCH", 90),
        "llm_request_timeout_seconds_synthesis": _env_int("LLM_REQUEST_TIMEOUT_SECONDS_SYNTHESIS", 240),
        "llm_request_timeout_seconds_correction": _env_int("LLM_REQUEST_TIMEOUT_SECONDS_CORRECTION", 180),
        "ddg_text_enabled": _env_bool("DDG_TEXT_ENABLED", True),
        "ddg_fallback_mode": os.getenv("DDG_FALLBACK_MODE", "provider_shift"),
        "ddg_suppress_impersonate_warnings": _env_bool("DDG_SUPPRESS_IMPERSONATE_WARNINGS", True),
        "stream_max_idle_seconds": _env_int("STREAM_MAX_IDLE_SECONDS", 120),
        "quota_pressure_mode": _env_bool("QUOTA_PRESSURE_MODE", False),
        "database_url": os.getenv("DATABASE_URL"),
    }
    if overrides:
        data.update(overrides)
    if "source_quality_bar" not in overrides:
        tier_mode = str(data.get("tier_policy_mode", "primary_only_strict")).strip().lower()
        if tier_mode == "primary_only_strict":
            data["source_quality_bar"] = "high_confidence"
        elif tier_mode == "hybrid_strict":
            data["source_quality_bar"] = "mixed"
        elif tier_mode == "broad":
            data["source_quality_bar"] = "broad"
    config = RunConfig(**data)
    _ensure_dirs(config)
    return config
