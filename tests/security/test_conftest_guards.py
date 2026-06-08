"""
Security guard tests for tests/conftest.py — ensures pytest can never
wipe a dev or production database.

TDD: these tests are written RED first. They go GREEN once
_refuse_unsafe_test_db() is defined in tests/conftest.py and
settings.test_database_url is added to backend/config.py.

DPDP Act 2023 note: running Base.metadata.drop_all against a prod DB
containing clinic patient data would constitute unlawful data destruction.
These guards are a legal compliance control, not merely a quality bar.
"""
import pytest


def test_conftest_refuses_when_test_url_equals_prod(monkeypatch):
    """Guard 1: TEST_DATABASE_URL must differ from DATABASE_URL.

    If they are equal, drop_all would wipe the same DB the app reads/writes.
    """
    from backend.config import settings as s
    monkeypatch.setattr(s, "test_database_url", "postgresql+asyncpg://x:y@localhost/vachanam_dev")
    monkeypatch.setattr(s, "database_url", "postgresql+asyncpg://x:y@localhost/vachanam_dev")

    from tests.conftest import _refuse_unsafe_test_db
    with pytest.raises(BaseException):
        _refuse_unsafe_test_db()


def test_conftest_refuses_when_test_url_lacks_test_substring(monkeypatch):
    """Guard 2: TEST_DATABASE_URL name must contain '_test' or 'test_'.

    This is a human-readable sanity check — every test DB should signal
    its purpose in its name. A name like 'vachanam_dev' is not a test DB.
    """
    from backend.config import settings as s
    monkeypatch.setattr(s, "test_database_url", "postgresql+asyncpg://x:y@localhost/vachanam_dev")
    monkeypatch.setattr(s, "database_url", "postgresql+asyncpg://x:y@localhost/vachanam_prod")

    from tests.conftest import _refuse_unsafe_test_db
    with pytest.raises(BaseException):
        _refuse_unsafe_test_db()


def test_conftest_refuses_when_url_targets_neon(monkeypatch):
    """Guard 3: TEST_DATABASE_URL must not point at known cloud/prod hosts.

    neon.tech, fly.dev, render.com, aws.com, rds.amazonaws.com are all
    production-class hosts. A test DB should be on localhost or a
    dedicated test container.
    """
    from backend.config import settings as s
    monkeypatch.setattr(
        s,
        "test_database_url",
        "postgresql+asyncpg://x:y@db.neon.tech/vachanam_test",
    )

    from tests.conftest import _refuse_unsafe_test_db
    with pytest.raises(BaseException):
        _refuse_unsafe_test_db()


def test_conftest_accepts_local_test_db(monkeypatch):
    """Guard happy-path: a localhost URL with '_test' in the DB name is allowed.

    This is the canonical local dev setup:
      postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_test
    """
    from backend.config import settings as s
    monkeypatch.setattr(
        s,
        "test_database_url",
        "postgresql+asyncpg://x:y@localhost/vachanam_test",
    )
    monkeypatch.setattr(
        s,
        "database_url",
        "postgresql+asyncpg://x:y@localhost/vachanam_dev",
    )

    from tests.conftest import _refuse_unsafe_test_db
    _refuse_unsafe_test_db()  # must NOT raise
