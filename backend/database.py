import asyncio
from weakref import WeakKeyDictionary

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings


def _new_engine():
    return create_async_engine(
        settings.database_url,
        echo=settings.app_env == "development",
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


# Default engine — import-time consumers (migration tests, init_db). Session
# traffic goes through the loop-aware factory below instead.
engine = _new_engine()

# One engine per event loop. FastAPI runs a single loop so this is one entry.
# The LiveKit worker reuses a warm process but creates a FRESH event loop per
# call (job); asyncpg connections pooled on call #1's loop are dead on call
# #2's loop ("Future attached to a different loop") — which made every call
# after the first crash before the agent could answer. WeakKeyDictionary lets
# finished loops (and their engines) be garbage collected.
_loop_engines: WeakKeyDictionary = WeakKeyDictionary()


def get_loop_engine():
    """Engine bound to the CURRENTLY RUNNING event loop. Must be called from
    async context."""
    loop = asyncio.get_running_loop()
    eng = _loop_engines.get(loop)
    if eng is None:
        eng = _new_engine()
        _loop_engines[loop] = eng
    return eng


class _LoopAwareSessionFactory:
    """Drop-in replacement for the old module-level async_sessionmaker: every
    `AsyncSessionLocal()` call binds the session to the current loop's engine.
    Tests that monkeypatch backend.database.AsyncSessionLocal keep working —
    they replace this attribute wholesale."""

    def __call__(self, **kw) -> AsyncSession:
        factory = async_sessionmaker(
            get_loop_engine(), class_=AsyncSession, expire_on_commit=False
        )
        return factory(**kw)


AsyncSessionLocal = _LoopAwareSessionFactory()


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """No-op in production (Alembic handles schema). Useful for tests that bypass
    migrations and need raw `Base.metadata.create_all`. Production main.py calls
    this on startup; in prod the tables already exist so create_all is a no-op."""
    async with get_loop_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
