from __future__ import annotations

import os
import socket
import time
from urllib.parse import urlparse

from core.config import load_config
from main import run_research

try:
    from celery import Celery  # type: ignore[import-untyped]
except Exception:  # noqa: BLE001
    Celery = None


def _build_celery_app():
    if Celery is None:
        return None

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    broker = os.getenv("CELERY_BROKER_URL", redis_url)
    backend = os.getenv("CELERY_RESULT_BACKEND", redis_url)

    return Celery("cloud_hive", broker=broker, backend=backend)


celery_app = _build_celery_app()


def _broker_endpoint_from_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (6379 if parsed.scheme.startswith("redis") else 5672)
    return host, port


def _broker_tcp_ready(url: str, timeout_seconds: int) -> tuple[bool, str]:
    host, port = _broker_endpoint_from_url(url)
    try:
        with socket.create_connection((host, port), timeout=max(1, timeout_seconds)):
            return True, ""
    except OSError as exc:
        return False, f"Broker {host}:{port} is unreachable ({exc})."


def is_distributed_ready(*, timeout_seconds: int = 2) -> tuple[bool, str]:
    """Check broker reachability and worker liveness with tight timeout."""
    if celery_app is None:
        return False, "Celery is not installed."

    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    broker_ok, broker_reason = _broker_tcp_ready(broker, timeout_seconds)
    if not broker_ok:
        return False, broker_reason

    try:
        inspect = celery_app.control.inspect(timeout=max(1, timeout_seconds))
        pings = inspect.ping() if inspect is not None else None
    except Exception as exc:  # noqa: BLE001
        return False, f"Celery worker ping failed ({exc})."

    if not pings:
        return False, "No active Celery workers responded to ping."
    return True, ""


def dispatch_distributed_task(
    *,
    query: str,
    tenant_id: str,
    run_id: str | None = None,
):
    if celery_app is None or execute_research_task is None:
        raise RuntimeError("Distributed task is unavailable.")
    return execute_research_task.delay(query=query, run_id=run_id, tenant_id=tenant_id)


def wait_for_distributed_result(
    task,
    *,
    queue_wait_seconds: int = 90,
    result_timeout_seconds: int = 15,
    poll_interval_seconds: float = 1.0,
) -> dict:
    deadline = time.monotonic() + max(1, queue_wait_seconds)
    while time.monotonic() < deadline:
        if task.ready():
            return task.get(timeout=max(1, result_timeout_seconds))
        time.sleep(max(0.1, poll_interval_seconds))
    raise TimeoutError(f"Distributed queue wait exceeded {queue_wait_seconds}s.")


if celery_app is not None:
    # Ensure tasks are discovered
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )

    @celery_app.task(name="cloud_hive.execute_research_task", bind=True)
    def execute_research_task(self, query: str, run_id: str | None = None, tenant_id: str = "default") -> dict:
        """
        Execute a research task in a background worker.
        """
        # Load config with overrides for the specific task context
        overrides = {
            "interactive_hitl": False,
            "tenant_id": tenant_id
        }

        # If we have a run_id, we might want to use it (though run_research generates a new one usually)
        # For now, we let run_research generate its own ID, but we could pass it if supported.

        config = load_config(overrides)

        print(f"Worker executing research for tenant={tenant_id} query='{query}'")

        # Execute the synchronous research graph
        result = run_research(query, config=config)

        payload = result.model_dump(mode="json")
        if run_id:
            payload["requested_run_id"] = run_id

        return payload
else:
    execute_research_task = None  # type: ignore[assignment]
