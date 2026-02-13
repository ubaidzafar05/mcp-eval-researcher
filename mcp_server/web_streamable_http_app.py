from __future__ import annotations

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from core.config import load_config
from mcp_server.security import build_token_verifier, validate_http_security
from mcp_server.web_server import WebMCPServer

_config = load_config()
validate_http_security(_config)
_verifier = build_token_verifier(_config)
_auth = None
if _verifier is not None:
    base_url = f"http://{_config.mcp_http_host}:{_config.mcp_http_port_web}"
    _auth = AuthSettings(issuer_url=base_url, resource_server_url=base_url)
app = FastMCP(
    "web-mcp-http",
    host=_config.mcp_http_host,
    port=_config.mcp_http_port_web,
    streamable_http_path="/mcp",
    token_verifier=_verifier,
    auth=_auth,
)
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
    app.run(transport="streamable-http")


if __name__ == "__main__":
    main()
