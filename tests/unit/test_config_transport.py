from core.config import load_config


def test_transport_config_defaults_are_present():
    cfg = load_config({"interactive_hitl": False})
    assert cfg.mcp_mode in {"auto", "transport", "inprocess"}
    assert cfg.mcp_transport == "stdio"
    assert "mcp_server.web_stdio_app" in cfg.mcp_web_server_cmd
    assert "mcp_server.local_stdio_app" in cfg.mcp_local_server_cmd
    assert cfg.mcp_startup_timeout_seconds > 0
    assert cfg.mcp_call_timeout_seconds > 0
    assert cfg.expected_github_owner

