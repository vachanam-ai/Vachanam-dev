from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolCheckoutTimeout

import backend.database as database
from backend.database import is_transient_database_error


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_read_retries_once_on_connection_failure(monkeypatch):
    first = object()
    second = object()
    sessions = iter((first, second))
    monkeypatch.setattr(
        database,
        "AsyncSessionLocal",
        lambda: _SessionContext(next(sessions)),
    )
    monkeypatch.setattr(database.asyncio, "sleep", AsyncMock())
    calls = []

    async def operation(session):
        calls.append(session)
        if session is first:
            raise OperationalError("SELECT 1", {}, ConnectionError("dropped"))
        return "ok"

    assert await database.run_db_read(operation) == "ok"
    assert calls == [first, second]


def test_transient_detection_covers_pool_timeout_and_pooler_overload():
    # pool checkout timeout — the session pool was momentarily saturated
    assert is_transient_database_error(PoolCheckoutTimeout("QueuePool limit"))
    # Supabase pooler overload / auth circuit breaker messages
    for msg in [
        "too many authentication failures, new connections are temporarily blocked",
        "sorry, too many clients already",
        "remaining connection slots are reserved",
        "server closed the connection unexpectedly",
    ]:
        assert is_transient_database_error(OperationalError("SELECT 1", {}, Exception(msg))), msg
    # a plain data/logic error is NOT transient
    assert not is_transient_database_error(ValueError("bad input"))


@pytest.mark.asyncio
async def test_read_retries_up_to_three_attempts(monkeypatch):
    s1, s2, s3 = object(), object(), object()
    sessions = iter((s1, s2, s3))
    monkeypatch.setattr(
        database, "AsyncSessionLocal", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(database.asyncio, "sleep", AsyncMock())
    seen = []

    async def operation(session):
        seen.append(session)
        if session in (s1, s2):
            raise ConnectionError("blip")
        return "ok"

    assert await database.run_db_read(operation) == "ok"
    assert seen == [s1, s2, s3]  # recovered on the 3rd attempt


@pytest.mark.asyncio
async def test_read_does_not_retry_application_errors(monkeypatch):
    session = object()
    monkeypatch.setattr(
        database,
        "AsyncSessionLocal",
        lambda: _SessionContext(session),
    )
    calls = 0

    async def operation(_session):
        nonlocal calls
        calls += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await database.run_db_read(operation)
    assert calls == 1


@pytest.mark.asyncio
async def test_dispose_loop_engine_releases_call_pool(monkeypatch):
    loop = database.asyncio.get_running_loop()
    engine = AsyncMock()
    monkeypatch.setitem(database._loop_engines, loop, engine)

    await database.dispose_loop_engine()

    engine.dispose.assert_awaited_once()
    assert loop not in database._loop_engines
