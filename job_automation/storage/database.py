"""Database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from job_automation.paths import DB_PATH, ensure_dirs
from job_automation.storage.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_decision ON jobs(decision)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_canonical_url ON jobs(canonical_url)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_identity_hash ON jobs(identity_hash)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_source_portal ON jobs(source_portal)",
    "CREATE INDEX IF NOT EXISTS idx_portal_runs_portal ON portal_runs(source_portal)",
]

COLUMN_MIGRATIONS = [
    ("jobs", "company_url", "ALTER TABLE jobs ADD COLUMN company_url TEXT"),
]


def get_database_url() -> str:
    ensure_dirs()
    return f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(get_database_url(), echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def _apply_column_migrations(sync_conn) -> None:
    from sqlalchemy import text

    for table, column, statement in COLUMN_MIGRATIONS:
        rows = sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            sync_conn.execute(text(statement))


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_column_migrations)
        for statement in INDEX_STATEMENTS:
            await conn.exec_driver_sql(statement)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
