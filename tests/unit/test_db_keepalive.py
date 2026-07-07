"""Neon keepalive DSN transform (FIXLOG #285).

_keepalive_dsn turns the app's SQLAlchemy DATABASE_URL into an asyncpg-
connectable DSN: drop the +asyncpg driver tag and the libpq sslmode query
param (asyncpg takes ssl= separately). A bad transform would make the keepalive
ping fail silently and Neon would still cold-start.
"""
from agent.livekit_minimal.agent import _keepalive_dsn


def test_strips_asyncpg_driver_and_sslmode():
    raw = "postgresql+asyncpg://u:p@ep-x.neon.tech/neondb?sslmode=require"
    assert _keepalive_dsn(raw) == "postgresql://u:p@ep-x.neon.tech/neondb"


def test_keeps_other_query_params():
    raw = "postgresql+asyncpg://u:p@h/db?sslmode=require&application_name=agent"
    out = _keepalive_dsn(raw)
    assert out.startswith("postgresql://u:p@h/db")
    assert "sslmode" not in out
    assert "application_name=agent" in out


def test_no_sslmode_unchanged_scheme_swapped():
    assert _keepalive_dsn("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"


def test_strips_wrapping_quotes_and_space():
    assert _keepalive_dsn('  "postgresql+asyncpg://u:p@h/db"  ') == "postgresql://u:p@h/db"


def test_empty_returns_empty():
    assert _keepalive_dsn("") == ""
    assert _keepalive_dsn(None) == ""
