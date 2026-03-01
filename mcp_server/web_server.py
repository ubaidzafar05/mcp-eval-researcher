from __future__ import annotations

import json
import logging
import warnings
from typing import Any
from urllib.parse import quote_plus, urlparse, urlunparse

import httpx

from core.models import RetrievedDoc, RunConfig
from core.rate_limit import RetryPolicy, TokenBucketLimiter, call_with_retries
from core.source_quality import annotate_doc

try:
    from tavily import TavilyClient  # type: ignore[import-untyped]
except Exception:  # noqa: BLE001
    TavilyClient = None

try:
    # Prefer duckduckgo_search first to avoid ddgs curl_cffi impersonation warnings
    # (e.g. firefox_117 deprecation fallback noise) in local runtime logs.
    from duckduckgo_search import DDGS  # type: ignore[import-untyped]
except Exception:  # noqa: BLE001
    try:
        from ddgs import DDGS  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        DDGS = None

logger = logging.getLogger(__name__)
_IMPERSONATION_WARN_PATTERN = r"Impersonate .* does not exist"


def _canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
    )
    return urlunparse(normalized).rstrip("/")


def _dedupe_docs_by_url(docs: list[RetrievedDoc], k: int) -> list[RetrievedDoc]:
    seen_urls: set[str] = set()
    result: list[RetrievedDoc] = []
    for doc in docs:
        doc = annotate_doc(doc)
        key = _canonical_url(doc.url) or f"{doc.provider}:{doc.title.lower()}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        result.append(doc.model_copy(update={"url": _canonical_url(doc.url)}))
        if len(result) >= max(1, k):
            break
    return result


class WebMCPServer:
    def __init__(self, config: RunConfig):
        self.config = config
        self.tavily_limiter = TokenBucketLimiter(config.tavily_rpm)
        self.ddg_limiter = TokenBucketLimiter(config.ddg_rpm)
        self.firecrawl_limiter = TokenBucketLimiter(config.firecrawl_rpm)
        self.retry_policy = RetryPolicy(max_retries=config.max_retries)
        self._ddg_text_degraded = False
        self._ddg_degradation_reason = ""
        if config.ddg_suppress_impersonate_warnings:
            warnings.filterwarnings(
                "ignore",
                message=_IMPERSONATION_WARN_PATTERN,
            )
            logging.getLogger("ddgs").setLevel(logging.ERROR)
            logging.getLogger("duckduckgo_search").setLevel(logging.ERROR)
            logging.getLogger("curl_cffi").setLevel(logging.ERROR)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "providers": {
                "tavily_key": bool(self.config.tavily_api_key),
                "firecrawl_key": bool(self.config.firecrawl_api_key),
            },
        }

    def tavily_search(self, query: str, k: int = 5) -> list[RetrievedDoc]:
        self.tavily_limiter.acquire()
        return call_with_retries(
            self._tavily_search_impl, query, k, policy=self.retry_policy
        )

    def _tavily_search_impl(self, query: str, k: int) -> list[RetrievedDoc]:
        if not self.config.tavily_api_key or TavilyClient is None:
            return self._fallback_docs(
                "tavily",
                query,
                reason="provider_unavailable",
                details="Tavily key or client is unavailable.",
            )

        client = TavilyClient(api_key=self.config.tavily_api_key)
        try:
            response = client.search(query=query, max_results=k, search_depth="advanced")
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            lowered = message.lower()
            reason = "provider_request_failed"
            if (
                "forbidden" in lowered
                or "usage limit" in lowered
                or "exceeds your plan" in lowered
                or "credits" in lowered
            ):
                reason = "provider_quota_exhausted"
            return self._fallback_docs("tavily", query, reason=reason, details=message[:320])

        docs: list[RetrievedDoc] = []
        for idx, item in enumerate(response.get("results", []), start=1):
            docs.append(
                annotate_doc(RetrievedDoc(
                    provider="tavily",
                    title=item.get("title", f"Tavily Result {idx}"),
                    url=_canonical_url(item.get("url", "")),
                    snippet=item.get("content", "")[:280],
                    content=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                ))
            )
        cleaned = _dedupe_docs_by_url(docs, k)
        return cleaned or self._fallback_docs(
            "tavily",
            query,
            reason="empty_provider_results",
            details="Tavily returned no usable results after normalization.",
        )

    def ddg_search(self, query: str, k: int = 5) -> list[RetrievedDoc]:
        self.ddg_limiter.acquire()
        return call_with_retries(self._ddg_search_impl, query, k, policy=self.retry_policy)

    def _ddg_search_impl(self, query: str, k: int) -> list[RetrievedDoc]:
        docs: list[RetrievedDoc] = []
        if self.config.ddg_text_enabled and not self._ddg_text_degraded:
            docs = self._ddg_text_search(
                query,
                k=max(k, 8 if self.config.research_depth == "deep" else k),
            )
        fallback_mode = self.config.ddg_fallback_mode
        if not docs and fallback_mode in {"instant_only", "mixed"}:
            docs = self._ddg_instant_answer_search(query, k)
        cleaned = _dedupe_docs_by_url(docs, k)
        if self._ddg_text_degraded and fallback_mode == "provider_shift" and not cleaned:
            return self._fallback_docs(
                "ddg",
                query,
                reason=self._ddg_degradation_reason or "provider_degraded_ddg_impersonation",
                details="DDG text mode disabled for this run after impersonation compatibility issue.",
            )
        return cleaned or self._fallback_docs(
            "ddg",
            query,
            reason=self._ddg_degradation_reason or "empty_provider_results",
            details="DuckDuckGo returned no usable results after normalization.",
        )

    def _ddg_text_search(self, query: str, k: int) -> list[RetrievedDoc]:
        if DDGS is None:
            return []

        docs: list[RetrievedDoc] = []
        search_queries = [query]
        if self.config.research_depth == "deep":
            search_queries.append(f"{query} analysis")
        elif self.config.research_depth == "balanced":
            search_queries.append(f"{query} overview")

        for ddg_query in search_queries[:2]:
            try:
                with DDGS(timeout=8) as ddgs:
                    results = list(ddgs.text(ddg_query, max_results=max(4, min(12, k))))
                for item in results:
                    title = str(item.get("title", "")).strip() or "DuckDuckGo result"
                    url = _canonical_url(str(item.get("href", "")).strip())
                    body = str(item.get("body", "")).strip()
                    if not url:
                        continue
                    docs.append(
                        annotate_doc(RetrievedDoc(
                            provider="ddg",
                            title=title,
                            url=url,
                            snippet=body[:280],
                            content=body,
                            score=0.52,
                        ))
                    )
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                if "impersonate" in message and "does not exist" in message:
                    self._ddg_text_degraded = True
                    self._ddg_degradation_reason = "provider_degraded_ddg_impersonation"
                    logger.warning("DDG text degraded due to impersonation compatibility issue.")
                    break
                continue
            if len(docs) >= k * 2:
                break
        return docs

    def _ddg_instant_answer_search(self, query: str, k: int) -> list[RetrievedDoc]:
        # Fallback no-key DDG path via Instant Answer + related topics.
        url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
        with httpx.Client(timeout=8.0) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
        docs: list[RetrievedDoc] = []
        abstract = payload.get("AbstractText") or ""
        if abstract:
            docs.append(
                annotate_doc(RetrievedDoc(
                    provider="ddg",
                    title=payload.get("Heading") or "DuckDuckGo Instant Answer",
                    url=_canonical_url(payload.get("AbstractURL") or ""),
                    snippet=abstract[:280],
                    content=abstract,
                    score=0.6,
                ))
            )
        for item in payload.get("RelatedTopics", [])[: max(0, k - len(docs))]:
            if isinstance(item, dict) and item.get("Text"):
                docs.append(
                    annotate_doc(RetrievedDoc(
                        provider="ddg",
                        title=item.get("Text", "")[:80] or "DuckDuckGo Related Topic",
                        url=_canonical_url(item.get("FirstURL", "")),
                        snippet=item.get("Text", "")[:280],
                        content=item.get("Text", ""),
                        score=0.4,
                    ))
                )
        return docs

    def firecrawl_extract(self, url_or_query: str, mode: str = "extract") -> list[RetrievedDoc]:
        self.firecrawl_limiter.acquire()
        return call_with_retries(
            self._firecrawl_extract_impl,
            url_or_query,
            mode,
            policy=self.retry_policy,
        )

    def _firecrawl_extract_impl(self, url_or_query: str, mode: str) -> list[RetrievedDoc]:
        if not self.config.firecrawl_api_key:
            return self._fallback_docs(
                "firecrawl",
                url_or_query,
                reason="provider_unavailable",
                details="Firecrawl API key is unavailable.",
            )

        endpoint = "https://api.firecrawl.dev/v1/scrape"
        body = {"url": url_or_query, "formats": ["markdown"]}
        headers = {
            "Authorization": f"Bearer {self.config.firecrawl_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(endpoint, headers=headers, content=json.dumps(body))
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data", {})
        markdown = data.get("markdown", "")
        title = (data.get("metadata") or {}).get("title", "Firecrawl Extract")
        return [annotate_doc(RetrievedDoc(
                provider="firecrawl",
                title=title,
                url=_canonical_url(url_or_query),
                snippet=markdown[:280],
                content=markdown,
                score=0.7 if mode == "extract" else 0.5,
            ))]

    @staticmethod
    def _fallback_docs(
        provider: str,
        query: str,
        *,
        reason: str = "provider_unavailable",
        details: str = "",
    ) -> list[RetrievedDoc]:
        return [annotate_doc(RetrievedDoc(
                provider="fallback",
                title=f"{provider.upper()} fallback result",
                url="",
                snippet=f"No live {provider} result available. Query: {query}",
                content=f"Fallback context for query: {query}.",
                score=0.1,
                meta={
                    "fallback_provider": provider,
                    "fallback_reason": reason,
                    "fallback_details": details,
                },
            ))]
