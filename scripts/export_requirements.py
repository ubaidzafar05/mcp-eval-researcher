from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_poetry_command() -> list[str]:
    env_bin = os.getenv("POETRY_BIN", "").strip()
    if env_bin:
        return [env_bin]

    py_path = Path(sys.executable)
    sibling_candidates = [py_path.with_name("poetry.exe"), py_path.with_name("poetry")]
    for candidate in sibling_candidates:
        if candidate.exists():
            return [str(candidate)]

    found = shutil.which("poetry")
    if found:
        return [found]

    return [sys.executable, "-m", "poetry"]


def export_requirements(output_path: str = "requirements.txt") -> None:
    target = Path(output_path)
    cmd = _resolve_poetry_command() + [
        "export",
        "--with",
        "dev",
        "--without-hashes",
        "--format",
        "requirements.txt",
        "--output",
        str(target),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    output = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    try:
        export_requirements(output)
        print(f"Exported requirements to {output}")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Failed to export requirements: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
