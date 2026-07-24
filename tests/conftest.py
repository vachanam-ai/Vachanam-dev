# One-time local setup (run once after cloning or on first pytest run):
#
#   docker exec vachanam-postgres-1 psql -U vachanam -d vachanam_dev -c "CREATE DATABASE vachanam_test;"
#
# This conftest deliberately does NOT auto-create the DB from Python to avoid
# race conditions when multiple pytest workers start simultaneously.
# After creating it, the DB is persistent; the fixture creates/drops tables
# per test function, not the database itself.

import os

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# EMAIL FUSE must exist at the environment layer before backend.config is
# imported. Some tests intentionally reload that module; mutating only the
# original Settings singleton lets a reload repopulate production credentials
# from the developer .env and makes later tests capable of sending real mail.
os.environ["RESEND_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""

from backend.models.schema import Base
from backend.config import settings
import backend.database as _db_module

# Tests use the LOCAL Docker Redis (docker-compose `redis` service), never prod
# Upstash. Reasons: (1) the time-based rate-limit tests assume low latency — 60
# requests must finish well inside the 60s window, which fails against Upstash
# from a dev box (~hundreds of ms/request) so the limit is never reached;
# (2) hermetic + flushable per test; (3) never burns the Upstash free-tier
# command quota. The limiter reads settings.redis_url lazily, so overriding it
# here (before any test runs) repoints both the limiter and the `redis` fixture.
settings.redis_url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")

# EMAIL FUSE (FIXLOG #369, sibling of the #324 DB fuse): the local .env
# carries the LIVE Resend key, and every full-suite run was REALLY mailing
# support@vachanam.in ("Demo request — Sunrise Dental", receipts to fake
# addresses...) because tests exercised the ticket/receipt paths for real.
# Every sender early-returns on an empty key/host. The pre-import environment
# fuse survives backend.config reloads; these assignments are defense in depth
# for the singleton imported by modules during collection. Tests that assert
# payloads mock the transport themselves and never rely on the real key.
settings.resend_api_key = ""
settings.smtp_host = ""

# PREFETCH FUSE (2026-07-24): the #5 tool prefetch fires route_to_doctor (a REAL
# Gemini routing call) from on_user_turn_completed on any booking-intent turn.
# Off by default in tests so exercising the turn hook never makes a live LLM call
# or leaks a background task; test_tool_prefetch re-enables it per-test.
settings.voice_tool_prefetch = False

# The real DATABASE_URL as loaded from .env — captured BEFORE the fuse below
# overwrites it, so _refuse_unsafe_test_db can still compare against it.
_ORIG_DATABASE_URL = settings.database_url


def _refuse_unsafe_test_db() -> None:
    """Hard-fail pytest if TEST_DATABASE_URL could point at a dev or prod DB.

    This is a DPDP Act 2023 compliance control. Running Base.metadata.drop_all
    against a production DB containing clinic patient data would constitute
    unlawful data destruction and expose Vachanam to criminal liability.

    Guards (any failure → pytest.fail with explicit reason):
      1. TEST_DATABASE_URL must be set.
      2. TEST_DATABASE_URL must differ from DATABASE_URL.
      3. TEST_DATABASE_URL must contain '_test' or 'test_' in the DB name.
      4. TEST_DATABASE_URL must not target known cloud/prod hosts.
      5. TEST_DATABASE_URL must not contain 'prod' or 'production'.

    Raises:
        pytest.fail — which raises _pytest.outcomes.Failed (a BaseException subclass).
                      This is intentional: the test run aborts, not merely errors.
    """
    url = settings.test_database_url

    if not url:
        pytest.fail("TEST_DATABASE_URL is not set — cannot run DB tests safely")

    if url == _ORIG_DATABASE_URL:
        # Strip password from URL before displaying (basic sanitisation).
        # Compared against the ORIGINAL .env DATABASE_URL — the module-level
        # fuse rewrites settings.database_url to the test URL, so comparing
        # against settings.database_url here would always (wrongly) fail.
        safe_url = _sanitize_url(url)
        pytest.fail(
            f"REFUSING to run tests against non-test DB: "
            f"TEST_DATABASE_URL equals DATABASE_URL ({safe_url}). "
            f"Running drop_all here would destroy dev/prod clinic data."
        )

    if "_test" not in url and "test_" not in url:
        safe_url = _sanitize_url(url)
        pytest.fail(
            f"REFUSING to run tests: TEST_DATABASE_URL must contain '_test' or 'test_' "
            f"to signal it is a dedicated test database (got: {safe_url}). "
            f"Rename your DB to include the test marker."
        )

    unsafe_hosts = [
        "neon.tech",
        "fly.dev",
        "render.com",
        "aws.com",
        "rds.amazonaws.com",
    ]
    for host in unsafe_hosts:
        if host in url:
            pytest.fail(
                f"REFUSING to run tests: TEST_DATABASE_URL targets potential prod host "
                f"'{host}' — {_sanitize_url(url)}. "
                f"Tests must run against a local or dedicated test container."
            )

    if "prod" in url.lower() or "production" in url.lower():
        pytest.fail(
            f"REFUSING to run tests: TEST_DATABASE_URL contains 'prod'/'production' — "
            f"{_sanitize_url(url)}. "
            f"This strongly suggests a production database. Aborting."
        )


def _sanitize_url(url: str) -> str:
    """Return the URL with the password replaced by '***' for safe logging.

    Handles the pattern  scheme://user:password@host/db
    If the URL does not match this pattern it is returned unchanged.
    """
    import re
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)


# ── HARD FUSE (FIXLOG #324): no test can EVER reach the real DATABASE_URL. ───
# Root cause 2026-07-12: tests that hit the app through an ASGI client WITHOUT
# requesting the `db` fixture left backend.database bound to .env DATABASE_URL
# (which on the dev box is Neon PROD) — every full-suite run posted junk
# "I am stuck, help" tickets into the LIVE support desk. The `db` fixture's
# rebinding is opt-in per test; this fuse is unconditional and runs at conftest
# import, before any test executes:
#   1. validate TEST_DATABASE_URL (same guards the db fixture uses),
#   2. overwrite settings.database_url with the test URL,
#   3. rebind backend.database.engine + AsyncSessionLocal to the test DB.
# A test that forgets `db` now fails loudly on missing tables instead of
# silently writing to production. DPDP: prod patient data is unreachable from
# the test process, full stop.
_refuse_unsafe_test_db()
settings.database_url = settings.test_database_url
_db_module.engine = create_async_engine(
    settings.test_database_url, echo=False, poolclass=NullPool
)
_db_module.AsyncSessionLocal = async_sessionmaker(
    _db_module.engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="function")
async def db():
    """Async SQLAlchemy session bound to the TEST database.

    Runs on settings.test_database_url (never settings.database_url).
    Hard-fails if any safety guard trips (see _refuse_unsafe_test_db).

    Lifecycle per test function:
      1. Run safety guards — abort if any trip.
      2. Dispose the module-level engine (per-loop pool isolation).
      3. Build a fresh engine pointing at vachanam_test.
      4. create_all  — build schema on vachanam_test.
      5. Patch _db_module.engine + _db_module.AsyncSessionLocal.
      6. yield session — test body runs.
      7. rollback     — undo any uncommitted writes.
      8. Restore original module-level engine + session factory.
      9. drop_all     — wipe tables so next test starts clean.
     10. dispose      — release all connections.

    Engine pools bind connections to the event loop they first ran in;
    pytest-asyncio (mode=auto) gives each test its own loop, so a pooled
    connection from a previous test fails with "Event loop is closed" if
    reused. Disposing forces a fresh pool per test.

    The fixture also patches _db_module.engine and _db_module.AsyncSessionLocal
    so that code calling AsyncSessionLocal() directly (e.g. test_concurrent_tokens)
    also lands on the test DB rather than vachanam_dev.
    """
    _refuse_unsafe_test_db()

    # Dispose the production-pointing module engine before we take over.
    await _db_module.engine.dispose()

    # NullPool: each session/connection is fresh and fully released on close, so
    # overlapping sessions in one test (the fixture's session + an endpoint's
    # get_db session + a job's session) never reuse one asyncpg connection across
    # pytest-asyncio's function-scoped event loops. Without this, certain multi-file
    # orderings tripped asyncpg "another operation is in progress" (a connection
    # reused mid-flight). Tests that fan out many concurrent sessions (e.g. the
    # 100-caller token race) gate their own concurrency with a semaphore so NullPool
    # never opens more connections at once than Postgres max_connections allows.
    engine = create_async_engine(settings.test_database_url, echo=False, poolclass=NullPool)
    # A session-level advisory lock serializes schema DDL across pytest workers
    # and interrupted prior runs. Rebuild first so orphaned PostgreSQL enum
    # types cannot make create_all fail with DuplicateObject.
    ddl_conn = await engine.connect()
    await ddl_conn.execute(text("SELECT pg_advisory_lock(86722419)"))
    await ddl_conn.commit()
    async with ddl_conn.begin():
        await ddl_conn.run_sync(Base.metadata.drop_all)
        await ddl_conn.run_sync(Base.metadata.create_all)

    test_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Save originals so we can restore after the test.
    _orig_engine = _db_module.engine
    _orig_session_local = _db_module.AsyncSessionLocal

    # Patch the module-level names in backend.database so attribute lookups
    # (backend.database.AsyncSessionLocal) resolve to the test DB.
    _db_module.engine = engine
    _db_module.AsyncSessionLocal = test_session_factory

    # Also patch any test modules that did `from backend.database import AsyncSessionLocal`
    # at import time — those hold their own local binding that won't see the patch above.
    import sys
    _patched_modules: list[tuple[object, str, object]] = []
    for _mod in list(sys.modules.values()):
        if _mod is not None and getattr(_mod, "AsyncSessionLocal", None) is _orig_session_local:
            _patched_modules.append((_mod, "AsyncSessionLocal", _orig_session_local))
            setattr(_mod, "AsyncSessionLocal", test_session_factory)

    async with test_session_factory() as session:
        yield session
        await session.rollback()

    # Restore originals before teardown.
    _db_module.engine = _orig_engine
    _db_module.AsyncSessionLocal = _orig_session_local
    for _mod, _attr, _original in _patched_modules:
        setattr(_mod, _attr, _original)

    async with ddl_conn.begin():
        await ddl_conn.run_sync(Base.metadata.drop_all)
    await ddl_conn.execute(text("SELECT pg_advisory_unlock(86722419)"))
    await ddl_conn.close()
    await engine.dispose()
    await _db_module.engine.dispose()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def redis():
    from backend.middleware import rate_limit

    await rate_limit.close_rate_limiter()
    # Use settings.redis_url — no hardcoded URLs (tester.md rule 5).
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    # Pre-flush so a leaky previous test cannot pollute this one (tester.md rule 7).
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()
    await rate_limit.close_rate_limiter()
