from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

from core.models import RunConfig


class LocalMCPServer:
    def __init__(self, config: RunConfig, root: Path | None = None):
        self.config = config
        self.root = root or Path.cwd()
        self._excluded_roots = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "outputs",
            "logs",
            "data",
        }

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "root": str(self.root)}

    def _safe_path(self, path: str) -> Path:
        candidate = (self.root / path).resolve()
        if self.root.resolve() not in candidate.parents and candidate != self.root.resolve():
            raise ValueError("Path escapes project root.")
        return candidate

    def read_local_file(self, path: str) -> str:
        target = self._safe_path(path)
        return target.read_text(encoding="utf-8")

    def list_project_files(self, pattern: str = "*") -> list[str]:
        results: list[str] = []
        for file_path in self.root.rglob("*"):
            if any(part in self._excluded_roots for part in file_path.parts):
                continue
            if file_path.is_file() and fnmatch.fnmatch(file_path.name, pattern):
                results.append(str(file_path.relative_to(self.root)))
        return sorted(results)

    def code_search(self, pattern: str, max_results: int = 20) -> list[dict[str, str]]:
        rg = [
            "rg",
            "-n",
            "--color",
            "never",
            "-g",
            "!.git/**",
            "-g",
            "!.venv/**",
            "-g",
            "!__pycache__/**",
            "-g",
            "!.pytest_cache/**",
            "-g",
            "!.ruff_cache/**",
            "-g",
            "!outputs/**",
            "-g",
            "!logs/**",
            "-g",
            "!data/**",
            pattern,
            str(self.root),
        ]
        try:
            output = subprocess.check_output(rg, text=True, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            return []
        findings: list[dict[str, str]] = []
        for line in output.splitlines()[:max_results]:
            try:
                file_path, line_no, content = line.split(":", 2)
            except ValueError:
                continue
            findings.append(
                {"path": file_path, "line": line_no, "content": content.strip()}
            )
        return findings

    def write_report_output(self, run_id: str, content: str) -> str:
        out_dir = self.root / self.config.output_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "final_report.md"
        target.write_text(content, encoding="utf-8")
        return str(target)
