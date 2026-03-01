from __future__ import annotations

import re

from core.source_quality import prioritize_docs
from core.verification import RetrievalFilterStats, wide_then_hard_filter
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _extract_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    return match.group(0) if match else None


def create_research_firecrawl_node(runtime: GraphRuntime):
    def firecrawl_node(state: ResearchState) -> dict:
        if not state.get("firecrawl_requested", False):
            return {
                "firecrawl_docs": [],
                "logs": ["Firecrawl skipped (not requested by planner)."],
            }

        target = _extract_url(state["query"]) or state["query"]
        docs = runtime.mcp_client.call_web_tool("firecrawl_extract", target, "extract")
        query_profile = state.get("query_profile")
        aggregate_stats = RetrievalFilterStats(candidate_count=len(docs))
        if query_profile and runtime.config.crawl_strategy in {"wide_then_filter", "aggressive"}:
            docs, filter_stats = wide_then_hard_filter(
                docs,
                query=query_profile.normalized_query or state["query"],
                profile=query_profile,
                freshness_max_months=runtime.config.freshness_max_months,
                min_relevance=0.1,
            )
            aggregate_stats.filtered_count += filter_stats.filtered_count
            aggregate_stats.stale_count += filter_stats.stale_count
            aggregate_stats.off_topic_count += filter_stats.off_topic_count
            aggregate_stats.low_signal_count += filter_stats.low_signal_count
        source_quality_bar = (
            "high_confidence"
            if runtime.config.primary_source_policy == "strict"
            else "mixed"
            if runtime.config.primary_source_policy == "hybrid"
            else "broad"
        )
        docs = prioritize_docs(
            docs,
            source_quality_bar=source_quality_bar,
            min_tier_ab_sources=max(runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources)
            if runtime.config.primary_source_policy == "strict"
            else runtime.config.min_tier_ab_sources,
        )
        aggregate_stats.kept_count = len(docs)
        aggregate_stats.filtered_count = max(
            aggregate_stats.filtered_count,
            max(0, aggregate_stats.candidate_count - aggregate_stats.kept_count),
        )
        runtime.tracer.event(
            state["run_id"],
            "research_firecrawl",
            "Collected firecrawl docs",
            payload={"doc_count": len(docs), "retrieval_stats": aggregate_stats.as_dict()},
        )
        return {
            "firecrawl_docs": docs,
            "firecrawl_retrieval_stats": aggregate_stats.as_dict(),
            "logs": [f"Firecrawl researcher collected {len(docs)} docs."],
        }

    return firecrawl_node
