from __future__ import annotations

import difflib
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_requirements import export_requirements


def check_requirements_sync(target_file: str = "requirements.txt") -> tuple[bool, str]:
    target_path = Path(target_file)
    if not target_path.exists():
        return False, f"{target_file} does not exist."

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "requirements.tmp.txt"
        export_requirements(str(tmp_path))
        expected = tmp_path.read_text(encoding="utf-8").splitlines()
        actual = target_path.read_text(encoding="utf-8").splitlines()

    if expected == actual:
        return True, ""
    diff = "\n".join(
        difflib.unified_diff(
            actual,
            expected,
            fromfile=target_file,
            tofile=f"{target_file} (poetry export)",
            lineterm="",
        )
    )
    message = (
        "requirements.txt is out of sync with Poetry.\n"
        "Run: python -m scripts.export_requirements\n\n"
        f"{diff}"
    )
    return False, message


def main() -> int:
    ok, message = check_requirements_sync()
    if ok:
        print("requirements.txt is in sync with Poetry.")
        return 0
    print(message)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

