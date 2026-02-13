from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from core.models import Citation, EvalResult, RetrievedDoc, TaskSpec


class BaseState(TypedDict):
    run_id: str
    query: str
    started_at: str
    status: str
    logs: Annotated[list[str], add]


class ResearchState(BaseState, total=False):
    tasks: list[TaskSpec]
    tavily_docs: Annotated[list[RetrievedDoc], add]
    ddg_docs: Annotated[list[RetrievedDoc], add]
    firecrawl_docs: Annotated[list[RetrievedDoc], add]
    context_docs: Annotated[list[RetrievedDoc], add]
    memory_docs: Annotated[list[RetrievedDoc], add]
    report_draft: str
    final_report: str
    citations: Annotated[list[Citation], add]
    eval_result: EvalResult | None
    correction_count: int
    needs_correction: bool
    low_confidence: bool
    firecrawl_requested: bool
    hitl_decision: str
    hitl_retry_used: bool
    metrics: dict[str, float]
    artifacts_path: str
