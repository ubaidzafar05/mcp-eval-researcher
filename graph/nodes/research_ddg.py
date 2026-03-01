from __future__ import annotations

from urllib.parse import urlparse

from core.citations import normalize_url
from core.models import TaskSpec
from core.query_profile import safe_analysis_policy
from core.source_quality import prioritize_docs
from core.verification import RetrievalFilterStats, wide_then_hard_filter
from graph.runtime import GraphRuntime
from graph.state import ResearchState


def _expand_queries(
    base_queries: list[str],
    query: str,
    *,
    deep: bool,
    facets: list[str],
    policy: str,
) -> list[str]:
    queries = list(dict.fromkeys([*base_queries, query]))
    facet_hint = " ".join(facets[:4]).strip()
    if deep:
        queries.extend(
            [
                f"{query} implementation approaches operational implications {facet_hint}".strip(),
                f"{query} independent analysis benchmark results {facet_hint}".strip(),
                f"{query} alternative interpretation criticism limitations".strip(),
            ]
        )
    if policy != "standard":
        queries.append(f"{query} abuse prevention policy and controls".strip())
    return list(dict.fromkeys(queries))


def _tier_ab_count(docs: list) -> int:
    return sum(
        1
        for doc in docs
        if str((getattr(doc, "meta", {}) or {}).get("source_tier", "unknown")) in {"A", "B"}
    )


def _peak_refocus_queries(query: str, facets: list[str]) -> list[str]:
    facet_hint = " ".join(facets[:4]).strip()
    return [
        f"{query} site:arxiv.org OR site:nature.com OR site:science.org {facet_hint}".strip(),
        f"{query} site:gov OR site:edu official benchmark report {facet_hint}".strip(),
        f"{query} standards documentation evaluation methodology {facet_hint}".strip(),
    ]


def _normalize_docs(raw_docs: list, *, deep: bool) -> list:
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    max_per_domain = 8 if deep else 3
    min_text_len = 80 if deep else 60
    filtered: list = []

    def _append_doc(doc, *, enforce_text_len: bool) -> bool:
        url = normalize_url(getattr(doc, "url", ""))
        if not url:
            return False
        text = f"{getattr(doc, 'snippet', '')} {getattr(doc, 'content', '')}".strip()
        if enforce_text_len and len(text) < min_text_len:
            return False
        if url in seen_urls:
            return False
        domain = (urlparse(url).netloc or "unknown").lower()
        if domain_counts.get(domain, 0) >= max_per_domain:
            return False
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        seen_urls.add(url)
        filtered.append(doc.model_copy(update={"url": url}))
        return True

    for doc in raw_docs:
        _append_doc(doc, enforce_text_len=True)

    # Keep provider lane alive in deep mode when snippets are short but URLs are valid.
    if deep and len(filtered) < 3:
        for doc in raw_docs:
            if len(filtered) >= 3:
                break
            _append_doc(doc, enforce_text_len=False)
    return filtered


def create_research_ddg_node(runtime: GraphRuntime):
    def ddg_node(state: ResearchState) -> dict:
        tasks = state.get("tasks", [])
        deep = runtime.config.research_depth == "deep" or runtime.config.research_mode == "peak"
        peak_mode = runtime.config.research_mode == "peak"
        query_profile = state.get("query_profile")
        effective_query = (
            query_profile.normalized_query
            if query_profile and query_profile.normalized_query
            else state["query"]
        )
        facets = list(query_profile.domain_facets) if query_profile else []
        policy = safe_analysis_policy(
            query_profile, dual_use_depth=runtime.config.dual_use_depth
        ) if query_profile else "standard"
        task_queries = [
            task.search_query
            for task in tasks
            if isinstance(task, TaskSpec) and task.tool_hint in {"ddg", "any"}
        ]
        if not task_queries:
            task_queries = [effective_query]
        task_queries = _expand_queries(
            task_queries,
            effective_query,
            deep=deep,
            facets=facets,
            policy=policy,
        )
        top_n_queries = 4 if peak_mode else 3 if deep else 2
        k = 10 if peak_mode else 8 if deep else 5

        docs = []
        aggregate_stats = RetrievalFilterStats()
        for query in task_queries[:top_n_queries]:
            docs.extend(runtime.mcp_client.call_web_tool("ddg_search", query, k))
        aggregate_stats.candidate_count = len(docs)
        provider_alerts: list[str] = []
        if any(
            getattr(doc, "provider", "") == "fallback"
            and str((doc.meta or {}).get("fallback_provider", "")).lower() == "ddg"
            and str((doc.meta or {}).get("fallback_reason", "")).lower() == "provider_degraded_ddg_impersonation"
            for doc in docs
        ):
            provider_alerts.append("provider_degraded_ddg_impersonation")
        normalized_docs = _normalize_docs(docs, deep=deep)
        docs = normalized_docs
        if runtime.config.crawl_strategy in {"wide_then_filter", "aggressive"}:
            docs, filter_stats = wide_then_hard_filter(
                docs,
                query=effective_query,
                profile=query_profile,
                freshness_max_months=runtime.config.freshness_max_months,
            )
            if not docs and normalized_docs:
                docs = normalized_docs[: min(len(normalized_docs), 6 if deep else 3)]
            aggregate_stats.filtered_count += filter_stats.filtered_count
            aggregate_stats.kept_count = filter_stats.kept_count
            aggregate_stats.stale_count += filter_stats.stale_count
            aggregate_stats.off_topic_count += filter_stats.off_topic_count
            aggregate_stats.low_signal_count += filter_stats.low_signal_count
        docs = prioritize_docs(
            docs,
            source_quality_bar=runtime.config.source_quality_bar,
            min_tier_ab_sources=runtime.config.min_tier_ab_sources,
        )
        if (
            runtime.config.source_quality_bar == "high_confidence"
            and _tier_ab_count(docs) < runtime.config.min_tier_ab_sources
            and normalized_docs
        ):
            ranked_seed = prioritize_docs(
                normalized_docs,
                source_quality_bar="broad",
                min_tier_ab_sources=0,
            )
            existing_urls = {
                normalize_url(getattr(doc, "url", ""))
                for doc in docs
                if normalize_url(getattr(doc, "url", ""))
            }
            for candidate in ranked_seed:
                tier = str((candidate.meta or {}).get("source_tier", "unknown")).upper()
                url = normalize_url(getattr(candidate, "url", ""))
                if tier not in {"A", "B"} or not url or url in existing_urls:
                    continue
                docs.insert(0, candidate)
                existing_urls.add(url)
                if _tier_ab_count(docs) >= runtime.config.min_tier_ab_sources:
                    break
        if peak_mode and _tier_ab_count(docs) < runtime.config.min_ab_sources:
            retry_docs: list = []
            for query in _peak_refocus_queries(effective_query, facets)[:2]:
                retry_docs.extend(runtime.mcp_client.call_web_tool("ddg_search", query, max(8, k)))
            aggregate_stats.candidate_count += len(retry_docs)
            retry_normalized = _normalize_docs(retry_docs, deep=True)
            retry_docs = retry_normalized
            if runtime.config.crawl_strategy in {"wide_then_filter", "aggressive"}:
                retry_docs, retry_stats = wide_then_hard_filter(
                    retry_docs,
                    query=effective_query,
                    profile=query_profile,
                    freshness_max_months=runtime.config.freshness_max_months,
                )
                if not retry_docs and retry_normalized:
                    retry_docs = retry_normalized[: min(len(retry_normalized), 6)]
                aggregate_stats.filtered_count += retry_stats.filtered_count
                aggregate_stats.stale_count += retry_stats.stale_count
                aggregate_stats.off_topic_count += retry_stats.off_topic_count
                aggregate_stats.low_signal_count += retry_stats.low_signal_count
            docs.extend(retry_docs)
            docs = _normalize_docs(docs, deep=True)
            docs = prioritize_docs(
                docs,
                source_quality_bar="high_confidence",
                min_tier_ab_sources=max(runtime.config.min_tier_ab_sources, runtime.config.min_ab_sources),
            )
        aggregate_stats.kept_count = len(docs)
        aggregate_stats.filtered_count = max(
            aggregate_stats.filtered_count,
            max(0, aggregate_stats.candidate_count - aggregate_stats.kept_count),
        )
        runtime.tracer.event(
            state["run_id"],
            "research_ddg",
            "Collected ddg docs",
            payload={
                "doc_count": len(docs),
                "query_count": min(len(task_queries), top_n_queries),
                "k": k,
                "retrieval_stats": aggregate_stats.as_dict(),
            },
        )
        return {
            "ddg_docs": docs,
            "ddg_retrieval_stats": aggregate_stats.as_dict(),
            "provider_alerts": provider_alerts,
            "logs": [f"DDG researcher collected {len(docs)} docs."],
        }

    return ddg_node
