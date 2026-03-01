from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from core.models import (
    Citation,
    EvalResult,
    QueryProfile,
    RetrievedDoc,
    SubReport,
    SubTopic,
    TaskSpec,
    TenantContext,
)


class BaseState(TypedDict):
    run_id: str
    query: str
    started_at: str
    status: str
    logs: Annotated[list[str], add]


class ResearchState(BaseState, total=False):
    tenant_context: TenantContext
    query_profile: QueryProfile
    tasks: list[TaskSpec]
    subtopics: list[SubTopic]
    shared_corpus_docs: Annotated[list[RetrievedDoc], add]
    sub_reports: Annotated[list[SubReport], add]
    subtopic_failures: Annotated[list[str], add]
    subtopic_metrics: dict[str, object]
    tavily_docs: Annotated[list[RetrievedDoc], add]
    ddg_docs: Annotated[list[RetrievedDoc], add]
    firecrawl_docs: Annotated[list[RetrievedDoc], add]
    tavily_retrieval_stats: dict[str, int]
    ddg_retrieval_stats: dict[str, int]
    firecrawl_retrieval_stats: dict[str, int]
    context_docs: Annotated[list[RetrievedDoc], add]
    memory_docs: Annotated[list[RetrievedDoc], add]
    provider_alerts: Annotated[list[str], add]
    source_index: dict[str, RetrievedDoc]
    report_draft: str
    final_report: str
    citations: list[Citation]
    eval_result: EvalResult | None
    correction_count: int
    needs_correction: bool
    low_confidence: bool
    firecrawl_requested: bool
    hitl_decision: str
    hitl_retry_used: bool
    metrics: dict[str, object]
    artifacts_path: str
