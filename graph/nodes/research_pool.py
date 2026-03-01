from __future__ import annotations

from core.citations import normalize_url
from core.models import RetrievedDoc
from core.source_quality import filter_docs_for_query, prioritize_docs
from graph.nodes.research_ddg import create_research_ddg_node
from graph.nodes.research_firecrawl import create_research_firecrawl_node
from graph.nodes.research_tavily import create_research_tavily_node
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return 0


def _merge_stats(*stats: dict[str, int] | None) -> dict[str, int]:
    merged = {
        "candidate_count": 0,
        "filtered_count": 0,
        "kept_count": 0,
        "stale_count": 0,
        "off_topic_count": 0,
        "low_signal_count": 0,
    }
    for item in stats:
        if not item:
            continue
        for key in merged:
            merged[key] += _as_int(item.get(key, 0))
    return merged


def _dedupe_docs(docs: list[RetrievedDoc]) -> list[RetrievedDoc]:
    seen_urls: set[str] = set()
    out: list[RetrievedDoc] = []
    for doc in docs:
        url = normalize_url(getattr(doc, "url", ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(doc.model_copy(update={"url": url}))
    return out


def create_research_pool_node(runtime: GraphRuntime):
    tavily_node = create_research_tavily_node(runtime)
    ddg_node = create_research_ddg_node(runtime)
    firecrawl_node = create_research_firecrawl_node(runtime)

    def research_pool_node(state: ResearchState) -> dict:
        tavily_updates = tavily_node(state)
        ddg_updates = ddg_node(state)
        firecrawl_updates = firecrawl_node(state)

        tavily_docs = list(tavily_updates.get("tavily_docs", []))
        ddg_docs = list(ddg_updates.get("ddg_docs", []))
        firecrawl_docs = list(firecrawl_updates.get("firecrawl_docs", []))
        provider_alerts = list(
            dict.fromkeys(
                [
                    *list(state.get("provider_alerts", [])),
                    *list(tavily_updates.get("provider_alerts", [])),
                    *list(ddg_updates.get("provider_alerts", [])),
                    *list(firecrawl_updates.get("provider_alerts", [])),
                ]
            )
        )

        shared_pool = _dedupe_docs([*tavily_docs, *ddg_docs, *firecrawl_docs])
        source_quality_bar = (
            "high_confidence"
            if runtime.config.primary_source_policy == "strict"
            else "mixed"
            if runtime.config.primary_source_policy == "hybrid"
            else "broad"
        )
        shared_pool = prioritize_docs(
            shared_pool,
            source_quality_bar=source_quality_bar,
            min_tier_ab_sources=max(runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources)
            if runtime.config.primary_source_policy == "strict"
            else runtime.config.min_tier_ab_sources,
        )
        off_topic_stats = {"off_topic_count": 0}
        query_profile = state.get("query_profile")
        if query_profile is not None:
            filtered_pool, off_topic_stats = filter_docs_for_query(
                shared_pool,
                query_profile,
                min_term_hits=2 if runtime.config.fact_mode == "strict" else 1,
            )
            # Keep strict filtering when we retained relevant documents.
            if filtered_pool:
                shared_pool = filtered_pool
        retrieval_stats = _merge_stats(
            tavily_updates.get("tavily_retrieval_stats"),
            ddg_updates.get("ddg_retrieval_stats"),
            firecrawl_updates.get("firecrawl_retrieval_stats"),
        )
        retrieval_stats["off_topic_count"] = max(
            retrieval_stats.get("off_topic_count", 0),
            off_topic_stats.get("off_topic_count", 0),
        )
        retrieval_stats["kept_count"] = len(shared_pool)
        retrieval_stats["filtered_count"] = max(
            retrieval_stats["filtered_count"],
            max(0, retrieval_stats["candidate_count"] - retrieval_stats["kept_count"]),
        )

        runtime.tracer.event(
            state["run_id"],
            "research_pool",
            "Shared retrieval pool prepared",
            payload={
                "shared_doc_count": len(shared_pool),
                "tavily_docs": len(tavily_docs),
                "ddg_docs": len(ddg_docs),
                "firecrawl_docs": len(firecrawl_docs),
                "retrieval_stats": retrieval_stats,
            },
        )
        metrics = dict(state.get("metrics", {}))
        provider_recovery_actions = list(metrics.get("provider_recovery_actions", []))
        if "provider_degraded_ddg_impersonation" in provider_alerts:
            provider_recovery_actions.append("ddg_text_disabled_for_run:provider_shift")
        if any(alert.startswith("provider_quota_exhausted:tavily") for alert in provider_alerts):
            provider_recovery_actions.append("tavily_quota_exhausted:provider_shift")
        metrics.update(
            {
                "retrieval_stats": retrieval_stats,
                "provider_alerts": provider_alerts,
                "provider_recovery_actions": list(dict.fromkeys(provider_recovery_actions)),
            }
        )
        return {
            **tavily_updates,
            **ddg_updates,
            **firecrawl_updates,
            "provider_alerts": provider_alerts,
            "shared_corpus_docs": shared_pool,
            "subtopic_metrics": {
                "retrieval_stats": retrieval_stats,
                "provider_alerts": provider_alerts,
            },
            "metrics": metrics,
            "logs": [f"Shared corpus prepared with {len(shared_pool)} docs."],
        }

    return research_pool_node
