from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote_plus

import httpx

from core.models import RetrievedDoc, RunConfig
from core.rate_limit import RetryPolicy, TokenBucketLimiter, call_with_retries

try:
    from tavily import TavilyClient
except Exception:  # noqa: BLE001
    TavilyClient = None


class WebMCPServer:
    def __init__(self, config: RunConfig):
        self.config = config
        self.tavily_limiter = TokenBucketLimiter(config.tavily_rpm)
        self.ddg_limiter = TokenBucketLimiter(config.ddg_rpm)
        self.firecrawl_limiter = TokenBucketLimiter(config.firecrawl_rpm)
        self.retry_policy = RetryPolicy(max_retries=config.max_retries)

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
            return self._fallback_docs("tavily", query)

        client = TavilyClient(api_key=self.config.tavily_api_key)
        response = client.search(query=query, max_results=k, search_depth="advanced")
        docs: list[RetrievedDoc] = []
        for idx, item in enumerate(response.get("results", []), start=1):
            docs.append(
                RetrievedDoc(
                    provider="tavily",
                    title=item.get("title", f"Tavily Result {idx}"),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:280],
                    content=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                )
            )
        return docs or self._fallback_docs("tavily", query)

    def ddg_search(self, query: str, k: int = 5) -> list[RetrievedDoc]:
        self.ddg_limiter.acquire()
        return call_with_retries(self._ddg_search_impl, query, k, policy=self.retry_policy)

    def _ddg_search_impl(self, query: str, k: int) -> list[RetrievedDoc]:
        # No-key DDG path via Instant Answer + related topics.
        url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
        with httpx.Client(timeout=8.0) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
        docs: list[RetrievedDoc] = []
        abstract = payload.get("AbstractText") or ""
        if abstract:
            docs.append(
                RetrievedDoc(
                    provider="ddg",
                    title=payload.get("Heading") or "DuckDuckGo Instant Answer",
                    url=payload.get("AbstractURL") or "",
                    snippet=abstract[:280],
                    content=abstract,
                    score=0.6,
                )
            )
        for item in payload.get("RelatedTopics", [])[: max(0, k - len(docs))]:
            if isinstance(item, dict) and item.get("Text"):
                docs.append(
                    RetrievedDoc(
                        provider="ddg",
                        title=item.get("Text", "")[:80] or "DuckDuckGo Related Topic",
                        url=item.get("FirstURL", ""),
                        snippet=item.get("Text", "")[:280],
                        content=item.get("Text", ""),
                        score=0.4,
                    )
                )
        return docs or self._fallback_docs("ddg", query)

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
            return self._fallback_docs("firecrawl", url_or_query)

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
        return [
            RetrievedDoc(
                provider="firecrawl",
                title=title,
                url=url_or_query,
                snippet=markdown[:280],
                content=markdown,
                score=0.7 if mode == "extract" else 0.5,
            )
        ]

    @staticmethod
    def _fallback_docs(provider: str, query: str) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(
                provider="fallback",
                title=f"{provider.upper()} fallback result",
                url="",
                snippet=f"No live {provider} result available. Query: {query}",
                content=f"Fallback context for query: {query}.",
                score=0.1,
                meta={"fallback_provider": provider},
            )
        ]

