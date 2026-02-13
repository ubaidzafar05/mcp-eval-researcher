import sys

import pytest

from core.config import load_config
from mcp_server.client import MultiServerClient


def test_mcp_client_auto_uses_transport():
    python = sys.executable
    cfg = load_config(
        {
            "interactive_hitl": False,
            "judge_provider": "stub",
            "mcp_mode": "auto",
            "mcp_web_server_cmd": f"{python} -m mcp_server.web_stdio_app",
            "mcp_local_server_cmd": f"{python} -m mcp_server.local_stdio_app",
        }
    )
    client = MultiServerClient.from_config(cfg)
    probe = client.startup_probe()
    try:
        assert probe.transport_enabled is True
        assert probe.transport_active is True
        docs = client.call_web_tool("ddg_search", "test query", 1)
        assert isinstance(docs, list)
    finally:
        client.close()


def test_mcp_client_auto_falls_back_when_transport_start_fails():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "judge_provider": "stub",
            "mcp_mode": "auto",
            "mcp_web_server_cmd": "python -m module_that_does_not_exist",
            "mcp_local_server_cmd": "python -m module_that_does_not_exist",
        }
    )
    client = MultiServerClient.from_config(cfg)
    probe = client.startup_probe()
    try:
        assert probe.transport_active is False
        assert probe.fallback_active is True
        docs = client.call_web_tool("ddg_search", "test query", 2)
        assert docs
    finally:
        client.close()


def test_mcp_client_transport_mode_fails_if_transport_unavailable():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "judge_provider": "stub",
            "mcp_mode": "transport",
            "mcp_web_server_cmd": "python -m module_that_does_not_exist",
            "mcp_local_server_cmd": "python -m module_that_does_not_exist",
        }
    )
    client = MultiServerClient.from_config(cfg)
    probe = client.startup_probe()
    try:
        assert probe.transport_active is False
        with pytest.raises(RuntimeError):
            client.call_web_tool("ddg_search", "test query", 1)
    finally:
        client.close()
