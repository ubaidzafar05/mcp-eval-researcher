from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.models import RetrievedDoc
from mcp_server.web_server import WebMCPServer


class ResearchToolPlugin(Protocol):
    name: str
    description: str

    def search(self, query: str, k: int) -> list[RetrievedDoc]:
        ...

    def estimate_cost(self, query: str, k: int) -> float:
        ...


@dataclass(slots=True)
class TavilyPlugin:
    server: WebMCPServer
    name: str = "tavily"
    description: str = "AI-focused web search"

    def search(self, query: str, k: int) -> list[RetrievedDoc]:
        return self.server.tavily_search(query=query, k=k)

    def estimate_cost(self, query: str, k: int) -> float:
        return 0.0


@dataclass(slots=True)
class DDGPlugin:
    server: WebMCPServer
    name: str = "ddg"
    description: str = "General free web search"

    def search(self, query: str, k: int) -> list[RetrievedDoc]:
        return self.server.ddg_search(query=query, k=k)

    def estimate_cost(self, query: str, k: int) -> float:
        return 0.0


def build_plugin_registry(server: WebMCPServer) -> dict[str, ResearchToolPlugin]:
    return {
        "tavily": TavilyPlugin(server),
        "ddg": DDGPlugin(server),
    }
