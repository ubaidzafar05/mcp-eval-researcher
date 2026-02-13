import asyncio

import pytest

from core.config import load_config
from mcp_server.security import build_token_verifier, validate_http_security


def test_validate_http_security_accepts_localhost_with_token():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "mcp_http_host": "127.0.0.1",
            "mcp_auth_token": "phase7-token",
        }
    )
    validate_http_security(cfg)


def test_validate_http_security_rejects_external_bind_by_default():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "mcp_http_host": "0.0.0.0",
            "mcp_auth_token": "phase7-token",
            "mcp_allow_external_bind": False,
        }
    )
    with pytest.raises(RuntimeError, match="External HTTP bind rejected"):
        validate_http_security(cfg)


def test_validate_http_security_rejects_missing_token_unless_insecure_enabled():
    cfg = load_config(
        {
            "interactive_hitl": False,
            "mcp_http_host": "127.0.0.1",
            "mcp_auth_token": None,
            "mcp_allow_insecure_http": False,
        }
    )
    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN is required"):
        validate_http_security(cfg)

    insecure_cfg = load_config(
        {
            "interactive_hitl": False,
            "mcp_http_host": "127.0.0.1",
            "mcp_auth_token": None,
            "mcp_allow_insecure_http": True,
        }
    )
    validate_http_security(insecure_cfg)


def test_build_token_verifier_returns_expected_result():
    cfg = load_config({"interactive_hitl": False, "mcp_auth_token": "good-token"})
    verifier = build_token_verifier(cfg)
    assert verifier is not None

    valid = asyncio.run(verifier.verify_token("good-token"))
    invalid = asyncio.run(verifier.verify_token("bad-token"))
    assert valid is not None
    assert invalid is None
