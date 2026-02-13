from __future__ import annotations

import socket

import pytest

from core.config import load_config
from mcp_server.client import MultiServerClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _base_http_config(**overrides: object):
    data = {
        "interactive_hitl": False,
        "judge_provider": "stub",
        "mcp_mode": "auto",
        "mcp_transport": "streamable-http",
        "mcp_http_host": "127.0.0.1",
        "mcp_http_port_web": _free_port(),
        "mcp_http_port_local": _free_port(),
        "mcp_auth_token": "phase7-token",
        "mcp_client_auth_token": "phase7-token",
        "mcp_startup_timeout_seconds": 15,
        "mcp_call_timeout_seconds": 10,
    }
    data.update(overrides)
    return load_config(data)


def test_mcp_client_streamable_http_success_path():
    cfg = _base_http_config()
    client = MultiServerClient.from_config(cfg)
    probe = client.startup_probe()
    try:
        assert probe.transport_enabled is True
        assert probe.transport_active is True
        docs = client.call_web_tool("tavily_search", "phase7 transport", 1)
        assert isinstance(docs, list)
        files = client.call_local_tool("list_project_files", "*.py")
        assert isinstance(files, list)
        assert files
    finally:
        client.close()


def test_mcp_client_auto_fallback_when_http_transport_is_unreachable():
    cfg = _base_http_config(
        mcp_http_external=True,
        mcp_http_web_url="http://127.0.0.1:65530/mcp",
        mcp_http_local_url="http://127.0.0.1:65531/mcp",
        mcp_auth_token=None,
        mcp_client_auth_token=None,
        mcp_startup_timeout_seconds=1,
        mcp_call_timeout_seconds=1,
    )
    client = MultiServerClient.from_config(cfg)
    probe = client.startup_probe()
    try:
        assert probe.transport_active is False
        assert probe.fallback_active is True
        docs = client.call_web_tool("tavily_search", "fallback path", 1)
        assert docs
    finally:
        client.close()


def test_mcp_client_transport_mode_auth_failure_does_not_fallback():
    cfg = _base_http_config(
        mcp_mode="transport",
        mcp_auth_token="good-token",
        mcp_client_auth_token="bad-token",
    )
    client = MultiServerClient.from_config(cfg)
    probe = client.startup_probe()
    try:
        assert probe.transport_enabled is True
        assert probe.transport_active is False
        assert probe.fallback_active is False
        with pytest.raises(RuntimeError):
            client.call_web_tool("tavily_search", "auth mismatch", 1)
    finally:
        client.close()
