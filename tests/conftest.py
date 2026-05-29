import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from backend.models.schema import Base
from backend.config import settings
import backend.database as _db_module


@pytest_asyncio.fixture(scope="function")
async def db():
    # Dispose the module-level engine in backend.database before AND after
    # each test. Engine pools bind connections to the event loop they first
    # ran in; pytest-asyncio (mode=auto) gives each test its own loop, so a
    # pooled connection from a previous test fails with "Event loop is
    # closed" if reused. Disposing forces a fresh pool per test.
    await _db_module.engine.dispose()

    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    await _db_module.engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def redis():
    # Use settings.redis_url — no hardcoded URLs (tester.md rule 5).
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    # Pre-flush so a leaky previous test cannot pollute this one (tester.md rule 7).
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()
