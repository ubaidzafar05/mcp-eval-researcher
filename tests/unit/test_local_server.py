from pathlib import Path

from core.config import load_config
from mcp_server.local_server import LocalMCPServer


def test_list_project_files_excludes_runtime_and_venv_dirs(tmp_path: Path):
    cfg = load_config({"interactive_hitl": False})
    server = LocalMCPServer(cfg, root=tmp_path)

    included = tmp_path / "src" / "keep.py"
    included.parent.mkdir(parents=True, exist_ok=True)
    included.write_text("print('ok')", encoding="utf-8")

    excluded = tmp_path / ".venv" / "ignored.py"
    excluded.parent.mkdir(parents=True, exist_ok=True)
    excluded.write_text("print('skip')", encoding="utf-8")

    files = server.list_project_files("*.py")
    assert "src\\keep.py" in files
    assert ".venv\\ignored.py" not in files
