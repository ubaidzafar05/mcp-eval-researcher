from __future__ import annotations

import os

from core.config import load_config
from main import run_research

try:
    from celery import Celery
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
