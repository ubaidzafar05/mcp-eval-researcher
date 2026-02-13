from __future__ import annotations

from core.config import load_config
from main import run_research

try:
    from celery import Celery
except Exception:  # noqa: BLE001
    Celery = None


def _build_celery_app():
    if Celery is None:
        return None
    return Celery("cloud_hive", broker="redis://redis:6379/0", backend="redis://redis:6379/1")


celery_app = _build_celery_app()


if celery_app is not None:

    @celery_app.task(name="cloud_hive.execute_research_task")  # type: ignore[misc]
    def execute_research_task(query: str, run_id: str | None = None, tenant_id: str = "default") -> dict:
        overrides = {"interactive_hitl": False, "tenant_id": tenant_id}
        config = load_config(overrides)
        result = run_research(query, config=config)
        payload = result.model_dump(mode="json")
        if run_id:
            payload["requested_run_id"] = run_id
        return payload
