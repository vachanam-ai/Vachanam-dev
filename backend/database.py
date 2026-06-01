from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """No-op in production (Alembic handles schema). Useful for tests that bypass
    migrations and need raw `Base.metadata.create_all`. Production main.py calls
    this on startup; in prod the tables already exist so create_all is a no-op."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
