"""Tests for database connection pool configuration.

Audit finding: create_async_engine had no explicit pool_size / max_overflow.
Defaults (5 + 10 = 15 max connections) are insufficient for 10 concurrent clinics
with ~3 sessions per tool invocation (30 peak connections).

Fix: pool_size=10, max_overflow=20 (total 30) added to create_async_engine call.

These are pure unit tests — no DB connection is opened. Pool parameters are read
directly from the engine object's pool attributes, which are populated at engine
creation time from the constructor arguments.
"""
from __future__ import annotations


def test_pool_size_configured() -> None:
    """Engine pool_size must be 10 and max_overflow must be 20.

    SQLAlchemy's AsyncEngine wraps a sync engine. The pool is accessible via
    engine.sync_engine.pool. QueuePool exposes:
      - pool.size()     → pool_size argument
      - pool.overflow() → current overflow count (0 at idle, NOT the max_overflow limit)

    To read max_overflow we inspect the private `_max_overflow` attribute on the pool,
    which is set from the constructor argument. This is the only stable way to assert
    the configured maximum — pool.overflow() is a runtime counter, not the config value.
    """
    import backend.database as _db_module

    engine = _db_module.engine
    pool = engine.sync_engine.pool

    actual_size = pool.size()
    actual_max_overflow = pool._max_overflow  # configured max, not current runtime counter

    assert actual_size == 10, (
        f"pool_size must be 10 for multi-clinic concurrency (got {actual_size}). "
        "Fix: add pool_size=10 to create_async_engine() in backend/database.py"
    )
    assert actual_max_overflow == 20, (
        f"max_overflow must be 20 for multi-clinic concurrency (got {actual_max_overflow}). "
        "Fix: add max_overflow=20 to create_async_engine() in backend/database.py"
    )


def test_pool_pre_ping_enabled() -> None:
    """pool_pre_ping must be True to detect stale connections in Neon serverless.

    Neon Postgres closes idle connections after ~5 minutes. Without pool_pre_ping,
    a stale pooled connection causes a cryptic 'SSL connection has been closed unexpectedly'
    error on the next query. pool_pre_ping sends a cheap SELECT 1 before checkout.
    """
    import backend.database as _db_module

    engine = _db_module.engine
    pool = engine.sync_engine.pool

    assert pool._pre_ping is True, (
        "pool_pre_ping must be True for Neon serverless compatibility. "
        "Fix: add pool_pre_ping=True to create_async_engine() in backend/database.py"
    )


def test_engine_is_async() -> None:
    """Sanity-check: engine must be an AsyncEngine (not a sync engine).

    Importing the module itself verifies the engine is created correctly at
    module load time. Using a sync engine would break all async route handlers.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    import backend.database as _db_module

    assert isinstance(_db_module.engine, AsyncEngine), (
        f"engine must be AsyncEngine, got {type(_db_module.engine).__name__}"
    )
