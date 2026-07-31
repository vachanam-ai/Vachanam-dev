import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar
from weakref import WeakKeyDictionary

from sqlalchemy.engine import make_url
from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    TimeoutError as PoolCheckoutTimeout,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from backend.config import settings

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _engine_config(raw_url: str) -> tuple[object, dict]:
    """Normalize PostgreSQL URLs and safely configure Supabase poolers."""
    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    if sslmode and "ssl" not in query:
        query["ssl"] = "require" if sslmode != "disable" else "disable"

    host = url.host or ""
    transaction_pooler = (
        host.endswith(".pooler.supabase.com") and url.port == 6543
    )
    session_pooler = host.endswith(".pooler.supabase.com") and url.port == 5432
    kwargs: dict = {}
    if transaction_pooler:
        query["prepared_statement_cache_size"] = "0"
        kwargs = {
            "poolclass": NullPool,
            "connect_args": {
                "statement_cache_size": 0,
                "timeout": 3,
                "command_timeout": 5,
            },
        }
    else:
        # Session mode has a project-wide 15-client ceiling on the free tier.
        # A voice call needs its main session plus at most one short read.
        kwargs = {
            "pool_size": 2 if session_pooler else 10,
            "max_overflow": 0 if session_pooler else 20,
            "pool_timeout": 3,
            "pool_recycle": 300,
            "connect_args": {"timeout": 3, "command_timeout": 5},
        }
    return url.set(query=query), kwargs


def _new_engine():
    url, pool_kwargs = _engine_config(settings.database_url)
    return create_async_engine(
        url,
        echo=settings.app_env == "development",
        pool_pre_ping=True,
        **pool_kwargs,
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


async def dispose_loop_engine() -> None:
    """Close every pooled connection owned by the current LiveKit call loop."""
    loop = asyncio.get_running_loop()
    eng = _loop_engines.pop(loop, None)
    if eng is not None:
        await eng.dispose()


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


# Supabase/Supavisor pooler pressure surfaces as a plain message on an
# otherwise-unclassified error (e.g. the auth circuit breaker, or the session
# pooler's client ceiling). Repeating on a fresh connection is safe and often
# succeeds once a slot frees, so treat these as transient too.
_POOLER_OVERLOAD_HINTS = (
    "too many",                 # too many connections / auth failures
    "temporarily blocked",      # ECIRCUITBREAKER new connections blocked
    "circuit breaker",
    "max client",               # pgbouncer max_client_conn
    "connection slots",         # postgres remaining connection slots
    "server closed the connection",
    "connection was closed",
    "connection is closed",
    "connection reset",
)


def is_transient_database_error(error: BaseException) -> bool:
    """Whether a failed read is safe to repeat on a fresh connection.

    Covers connection-level SQLAlchemy/asyncpg failures, a pool checkout
    timeout (the session pool was momentarily saturated), and Supabase pooler
    overload/breaker messages — all of which a fresh attempt can clear."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(
            current, (InterfaceError, OperationalError, PoolCheckoutTimeout)
        ):
            return True
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        if isinstance(current, (ConnectionError, OSError, asyncio.TimeoutError)):
            return True
        text = str(current).lower()
        if text and any(hint in text for hint in _POOLER_OVERLOAD_HINTS):
            return True
        current = current.__cause__ or current.__context__
    return False


async def run_db_read(
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    attempts: int = 3,
) -> T:
    """Run a read in a short session and retry only connection-level failures.

    A fresh session each attempt prevents one dropped long-lived call
    connection — or a momentarily saturated pool / a transient pooler blip —
    from poisoning a lookup: the retry reconnects and usually succeeds. Three
    attempts (was two) so a single reconnect + one pooler slot-free both get a
    chance before the caller is told anything. Writes deliberately do not use
    this helper because repeating an uncertain commit can duplicate data.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(1, attempts + 1):
        try:
            async with AsyncSessionLocal() as session:
                return await operation(session)
        except Exception as error:
            if attempt == attempts or not is_transient_database_error(error):
                raise
            logger.warning(
                "database_read_retry attempt=%d error=%s",
                attempt,
                type(error).__name__,
            )
            await asyncio.sleep(0.1 * attempt)
    raise AssertionError("unreachable")


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
