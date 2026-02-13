from __future__ import annotations

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from core.config import load_config
from mcp_server.local_server import LocalMCPServer
from mcp_server.security import build_token_verifier, validate_http_security

_config = load_config()
validate_http_security(_config)
_verifier = build_token_verifier(_config)
_auth = None
if _verifier is not None:
    base_url = f"http://{_config.mcp_http_host}:{_config.mcp_http_port_local}"
    _auth = AuthSettings(issuer_url=base_url, resource_server_url=base_url)
app = FastMCP(
    "local-mcp-http",
    host=_config.mcp_http_host,
    port=_config.mcp_http_port_local,
    streamable_http_path="/mcp",
    token_verifier=_verifier,
    auth=_auth,
)
_server = LocalMCPServer(_config)


@app.tool()
def read_local_file(path: str) -> str:
    return _server.read_local_file(path=path)


@app.tool()
def list_project_files(pattern: str = "*") -> list[str]:
    return _server.list_project_files(pattern=pattern)


@app.tool()
def code_search(pattern: str, max_results: int = 20) -> list[dict[str, str]]:
    return _server.code_search(pattern=pattern, max_results=max_results)


@app.tool()
def write_report_output(run_id: str, content: str) -> str:
    return _server.write_report_output(run_id=run_id, content=content)


def main() -> None:
    app.run(transport="streamable-http")


if __name__ == "__main__":
    main()
