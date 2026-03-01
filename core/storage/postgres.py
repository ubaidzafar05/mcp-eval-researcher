import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db.models import Event, Run
from core.models import RunConfig

logger = logging.getLogger(__name__)

class PostgresStorage:
    def __init__(self, config: RunConfig):
        self.config = config
        if not config.database_url:
            raise ValueError("database_url is required for PostgresStorage")

        self.engine = create_async_engine(config.database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def initialize(self):
        # In a real app, we might run migrations here or ensure connection
        pass

    async def close(self):
        await self.engine.dispose()

    async def create_run(self, run_id: str, query: str, tenant_id: str) -> None:
        async with self.async_session() as session:
            run = Run(
                run_id=run_id,
                tenant_id=tenant_id,
                query=query,
                status="created",
                created_at=datetime.utcnow()
            )
            session.add(run)
            await session.commit()

    async def update_run_status(self, run_id: str, status: str, result: dict | None = None) -> None:
        async with self.async_session() as session:
            stmt = update(Run).where(Run.run_id == run_id).values(
                status=status,
                updated_at=datetime.utcnow()
            )
            if result:
                 # Extract report if present
                report = result.get("final_report")
                # Store full result as artifacts
                stmt = stmt.values(report=report, artifacts=result)

            await session.execute(stmt)
            await session.commit()

    async def add_event(self, run_id: str, node: str, event_type: str, payload: dict) -> None:
        async with self.async_session() as session:
            event = Event(
                run_id=run_id,
                node=node,
                event_type=event_type,
                payload=payload,
                created_at=datetime.utcnow()
            )
            session.add(event)
            await session.commit()

    async def get_run(self, run_id: str) -> dict | None:
        async with self.async_session() as session:
            result = await session.execute(select(Run).where(Run.run_id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                return None
            return {
                "run_id": run.run_id,
                "tenant_id": run.tenant_id,
                "query": run.query,
                "status": run.status,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "artifacts": run.artifacts
            }
