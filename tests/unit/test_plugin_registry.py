from core.config import load_config
from mcp_server.plugin_registry import build_plugin_registry
from mcp_server.web_server import WebMCPServer


def test_plugin_registry_contains_default_plugins():
    cfg = load_config({"interactive_hitl": False})
    server = WebMCPServer(cfg)
    registry = build_plugin_registry(server)
    assert "tavily" in registry
    assert "ddg" in registry
    assert registry["tavily"].name == "tavily"
