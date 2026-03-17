"""provider_smoke_minimal.py — Minimal smoke test for LLM provider connectivity.

Verifies that the local Ollama instance is reachable and responds to
a simple chat completion request via the OpenAI-compatible /v1 endpoint.
"""
from __future__ import annotations

import sys

from core.config import load_config


def main() -> None:
    cfg = load_config({"interactive_hitl": False})
    print(f"Ollama endpoint: {cfg.ollama_endpoint}")
    print(f"Ollama model:    {cfg.ollama_model}")

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key="ollama",
            base_url=f"{cfg.ollama_endpoint}/v1",
            timeout=30,
        )
        resp = client.chat.completions.create(
            model=cfg.ollama_model,
            messages=[{"role": "user", "content": "Say hello in one word."}],
            temperature=0.0,
        )
        reply = (resp.choices[0].message.content or "").strip()
        print(f"✅ Ollama responded: {reply}")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ollama smoke test failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
