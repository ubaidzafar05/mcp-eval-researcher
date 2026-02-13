from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.config import load_config
from mcp_server.web_server import WebMCPServer

app = FastMCP("web-mcp")
_config = load_config()
_server = WebMCPServer(_config)


@app.tool()
def tavily_search(query: str, k: int = 5) -> list[dict]:
    docs = _server.tavily_search(query=query, k=k)
    return [doc.model_dump(mode="json") for doc in docs]


@app.tool()
def ddg_search(query: str, k: int = 5) -> list[dict]:
    docs = _server.ddg_search(query=query, k=k)
    return [doc.model_dump(mode="json") for doc in docs]


@app.tool()
def firecrawl_extract(url_or_query: str, mode: str = "extract") -> list[dict]:
    docs = _server.firecrawl_extract(url_or_query=url_or_query, mode=mode)
    return [doc.model_dump(mode="json") for doc in docs]


def main() -> None:
    app.run(transport="stdio")


if __name__ == "__main__":
    main()

