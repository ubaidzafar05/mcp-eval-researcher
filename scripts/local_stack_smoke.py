from __future__ import annotations

import socket
from dataclasses import dataclass

from core.config import load_config
from mcp_server.client import MultiServerClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(slots=True)
class SmokeResult:
    name: str
    ok: bool
    details: str


def _run_probe(name: str, overrides: dict[str, object]) -> SmokeResult:
    cfg = load_config({"interactive_hitl": False, "judge_provider": "stub"} | overrides)
    client = MultiServerClient.from_config(cfg)
    try:
        probe = client.startup_probe()
        if cfg.mcp_mode == "transport" and not probe.transport_active:
            return SmokeResult(name=name, ok=False, details=probe.fallback_reason or "transport inactive")
        if not probe.web_healthy or not probe.local_healthy:
            return SmokeResult(name=name, ok=False, details="one or more MCP servers unhealthy")
        return SmokeResult(
            name=name,
            ok=True,
            details=(
                f"transport_active={probe.transport_active}, "
                f"web_endpoint={probe.web_endpoint}, local_endpoint={probe.local_endpoint}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return SmokeResult(name=name, ok=False, details=str(exc))
    finally:
        client.close()


def run_smoke_suite() -> list[SmokeResult]:
    results: list[SmokeResult] = []
    results.append(
        _run_probe(
            "stdio-transport",
            {
                "mcp_mode": "transport",
                "mcp_transport": "stdio",
            },
        )
    )

    web_port = _free_port()
    local_port = _free_port()
    results.append(
        _run_probe(
            "http-transport",
            {
                "mcp_mode": "transport",
                "mcp_transport": "streamable-http",
                "mcp_http_host": "127.0.0.1",
                "mcp_http_port_web": web_port,
                "mcp_http_port_local": local_port,
                "mcp_auth_token": "local-smoke-token",
                "mcp_client_auth_token": "local-smoke-token",
                "mcp_allow_insecure_http": False,
                "mcp_allow_external_bind": False,
                "mcp_startup_timeout_seconds": 20,
                "mcp_call_timeout_seconds": 15,
            },
        )
    )
    return results


def main() -> int:
    results = run_smoke_suite()
    failed = [item for item in results if not item.ok]
    for item in results:
        status = "PASS" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.details}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
