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


def _groups_for_profile(profile: str) -> list[str]:
    normalized = (profile or "full").strip().lower()
    if normalized == "minimal":
        return ["dev"]
    if normalized == "balanced":
        return ["dev", "distributed", "storage"]
    return ["dev", "distributed", "observability", "storage", "eval"]


def export_requirements(output_path: str = "requirements.txt", *, profile: str = "full") -> None:
    target = Path(output_path)
    groups = ",".join(_groups_for_profile(profile))
    cmd = _resolve_poetry_command() + [
        "export",
        "--with",
        groups,
        "--without-hashes",
        "--format",
        "requirements.txt",
        "--output",
        str(target),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    output = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    profile = sys.argv[2] if len(sys.argv) > 2 else os.getenv("REQUIREMENTS_PROFILE", "full")
    try:
        export_requirements(output, profile=profile)
        print(f"Exported requirements to {output} (profile={profile})")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Failed to export requirements: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
