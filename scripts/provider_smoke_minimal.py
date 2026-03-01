from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import load_config
from graph.runtime import GraphRuntime
from mcp_server.web_server import WebMCPServer


@dataclass(slots=True)
class SmokeCheck:
    name: str
    ok: bool
    detail: str


def _check_tavily(web: WebMCPServer) -> SmokeCheck:
    if not web.config.tavily_api_key:
        return SmokeCheck("tavily", True, "SKIP (no key)")
    try:
        docs = web.tavily_search("site:example.com AI", k=1)
        return SmokeCheck("tavily", True, f"OK ({len(docs)} doc)")
    except Exception as exc:  # noqa: BLE001
        return SmokeCheck("tavily", False, f"FAIL ({exc})")


def _check_ddg(web: WebMCPServer) -> SmokeCheck:
    try:
        docs = web.ddg_search("AI research", k=1)
        return SmokeCheck("ddg", True, f"OK ({len(docs)} doc)")
    except Exception as exc:  # noqa: BLE001
        return SmokeCheck("ddg", False, f"FAIL ({exc})")


def _check_firecrawl(web: WebMCPServer) -> SmokeCheck:
    if not web.config.firecrawl_api_key:
        return SmokeCheck("firecrawl", True, "SKIP (no key)")
    try:
        docs = web.firecrawl_extract("https://example.com", mode="extract")
        return SmokeCheck("firecrawl", True, f"OK ({len(docs)} doc)")
    except Exception as exc:  # noqa: BLE001
        return SmokeCheck("firecrawl", False, f"FAIL ({exc})")


def _llm_ping(client: Any, provider: str, model: str) -> None:
    if provider in {"openai", "groq", "openrouter"}:
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with: ok"}],
            max_tokens=5,
            temperature=0,
        )
        return
    if provider == "anthropic":
        client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with: ok"}],
            temperature=0,
        )
        return
    if provider == "huggingface":
        client.chat_completion(
            messages=[{"role": "user", "content": "Reply with: ok"}],
            max_tokens=5,
            temperature=0,
        )
        return
    raise ValueError(f"Unsupported provider: {provider}")


def _check_llm(runtime: GraphRuntime, provider: str, model: str, enabled: bool) -> SmokeCheck:
    if not enabled:
        return SmokeCheck(provider, True, "SKIP (not configured)")
    try:
        client = runtime.get_llm_client(provider)
        _llm_ping(client, provider, model)
        return SmokeCheck(provider, True, "OK")
    except Exception as exc:  # noqa: BLE001
        return SmokeCheck(provider, False, f"FAIL ({exc})")


def run_minimal_smoke() -> list[SmokeCheck]:
    cfg = load_config({"interactive_hitl": False, "judge_provider": "stub"})
    runtime = GraphRuntime.from_config(cfg)
    web = WebMCPServer(cfg)
    checks: list[SmokeCheck] = []
    try:
        checks.append(_check_tavily(web))
        checks.append(_check_ddg(web))
        checks.append(_check_firecrawl(web))

        checks.append(
            _check_llm(
                runtime,
                "groq",
                cfg.groq_model,
                bool(cfg.groq_api_key and cfg.groq_api_key.strip()),
            )
        )
        checks.append(
            _check_llm(
                runtime,
                "openai",
                "gpt-4-turbo",
                bool(cfg.openai_api_key and cfg.openai_api_key.strip()),
            )
        )
        checks.append(
            _check_llm(
                runtime,
                "anthropic",
                "claude-sonnet-4",
                bool(cfg.anthropic_api_key and cfg.anthropic_api_key.strip()),
            )
        )
        checks.append(
            _check_llm(
                runtime,
                "openrouter",
                cfg.openrouter_model,
                bool(cfg.openrouter_api_key and cfg.openrouter_api_key.strip()),
            )
        )
        checks.append(
            _check_llm(
                runtime,
                "huggingface",
                cfg.huggingface_model,
                bool(cfg.hf_token and cfg.hf_token.strip()),
            )
        )
    finally:
        runtime.close()

    return checks


def main() -> int:
    checks = run_minimal_smoke()
    failed = [c for c in checks if not c.ok]
    for check in checks:
        prefix = "PASS" if check.ok else "FAIL"
        print(f"[{prefix}] {check.name}: {check.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
