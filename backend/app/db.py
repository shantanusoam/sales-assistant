"""Async SQLAlchemy engine/session plumbing. Schema lives in models.py, migrations in alembic/."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import Settings


class Base(DeclarativeBase):
    pass


def make_db(settings: Settings) -> tuple[AsyncEngine, callable, async_sessionmaker[AsyncSession]]:
    """One engine per app instance (never shared/cached across event loops — that causes
    cross-loop connection reuse and teardown races, e.g. under pytest). Returns
    (engine, get_db dependency, session factory for ad-hoc sessions outside a request)."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return engine, get_db, factory


async def create_all(engine: AsyncEngine) -> None:
    """Create tables directly from models (used by tests and first-run convenience; real
    deployments should use `alembic upgrade head` instead so schema changes are tracked)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
