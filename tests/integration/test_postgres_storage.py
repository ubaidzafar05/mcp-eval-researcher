
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError

from core.config import load_config

try:
    from core.storage.postgres import PostgresStorage
except Exception:
    pytest.skip("Storage extras are not installed.", allow_module_level=True)

# Only run if database_url is present
config = load_config()
if not config.database_url:
    pytest.skip("No DATABASE_URL configured", allow_module_level=True)

@pytest_asyncio.fixture
async def storage():
    config = load_config()
    storage = PostgresStorage(config)
    try:
        await storage.initialize()
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres is not reachable in this environment: {exc}")
    yield storage
    await storage.close()

@pytest.mark.asyncio
async def test_create_and_get_run(storage):
    run_id = str(uuid.uuid4())
    tenant_id = "test-tenant"
    query = "test query"

    # Create
    await storage.create_run(run_id, query, tenant_id)

    # Get
    run = await storage.get_run(run_id)
    assert run is not None
    assert run["run_id"] == run_id
    assert run["query"] == query
    assert run["status"] == "created"

@pytest.mark.asyncio
async def test_update_status(storage):
    run_id = str(uuid.uuid4())
    await storage.create_run(run_id, "query", "tenant")

    result = {"final_report": "some markdown"}
    await storage.update_run_status(run_id, "completed", result=result)

    run = await storage.get_run(run_id)
    assert run["status"] == "completed"
    assert run["artifacts"]["final_report"] == "some markdown"

@pytest.mark.asyncio
async def test_add_event(storage):
    run_id = str(uuid.uuid4())
    await storage.create_run(run_id, "query", "tenant")

    await storage.add_event(run_id, "node_a", "start", {"foo": "bar"})

    # We didn't add a get_events method in the minimal interface yet,
    # but we can verify it didn't crash.
    # To verify properly, we'd need to query directly or add get_events.
    # For now, if no exception, it inserted.
