"""Async database setup (aiosqlite locally, asyncpg in production)."""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def make_engine(url: str) -> AsyncEngine:
    if not is_sqlite(url):
        return create_async_engine(url, pool_pre_ping=True)
    if url.rstrip("/").endswith((":memory:", "sqlite+aiosqlite:")):
        raise ValueError("use a file-backed SQLite database (workers must share it)")
    engine = create_async_engine(url, connect_args={"timeout": 30})

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # readers never block the writer
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def init_db(engine: AsyncEngine) -> None:
    from . import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
