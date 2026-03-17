from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.config import load_config
from mcp_server.local_server import LocalMCPServer

app = FastMCP("local-mcp")
_config = load_config()
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
    app.run(transport="stdio")


if __name__ == "__main__":
    main()

