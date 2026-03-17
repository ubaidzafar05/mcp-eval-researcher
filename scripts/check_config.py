"""check_config.py — Quick sanity check for RunConfig loading."""
from __future__ import annotations

from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from core.config import load_config  # noqa: E402


def main() -> None:
    try:
        config = load_config()
        print(f"Ollama endpoint: {config.ollama_endpoint}")
        print(f"Ollama model: {config.ollama_model}")
        print(f"Judge provider: {config.judge_provider}")
        print("RunConfig attributes verified successfully.")
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
