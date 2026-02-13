from __future__ import annotations

from mcp.server.auth.provider import AccessToken, TokenVerifier

from core.models import RunConfig


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, expected_token: str):
        self.expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != self.expected_token:
            return None
        return AccessToken(token=token, client_id="cloud-hive", scopes=["mcp:tool"])


def validate_http_security(config: RunConfig) -> None:
    host = (config.mcp_http_host or "").strip().lower()
    allowed_local_hosts = {"127.0.0.1", "localhost"}
    if host not in allowed_local_hosts and not config.mcp_allow_external_bind:
        raise RuntimeError(
            "External HTTP bind rejected. Set MCP_ALLOW_EXTERNAL_BIND=true to override."
        )
    if not config.mcp_auth_token and not config.mcp_allow_insecure_http:
        raise RuntimeError(
            "MCP_AUTH_TOKEN is required for streamable-http unless "
            "MCP_ALLOW_INSECURE_HTTP=true."
        )


def build_token_verifier(config: RunConfig) -> TokenVerifier | None:
    if config.mcp_auth_token:
        return StaticTokenVerifier(config.mcp_auth_token)
    return None

