from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path


def cleanup_old_artifacts(paths: Iterable[str], ttl_days: int) -> int:
    cutoff = datetime.now(tz=UTC) - timedelta(days=max(1, ttl_days))
    deleted = 0
    for base in paths:
        root = Path(base)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*"), reverse=True):
            try:
                mtime = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=UTC
                )
                if mtime > cutoff:
                    continue
                if path.is_file():
                    path.unlink(missing_ok=True)
                    deleted += 1
                elif path.is_dir():
                    # Remove empty directories after file cleanup.
                    next(path.iterdir())
            except StopIteration:
                path.rmdir()
            except Exception:  # noqa: BLE001
                continue
    return deleted

