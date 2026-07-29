from sqlalchemy.pool import NullPool

from backend.database import _engine_config


def test_supabase_session_pooler_keeps_client_pool_and_enforces_asyncpg_tls():
    url, kwargs = _engine_config(
        "postgresql://user:p%40ss@aws-1-ap-south-1.pooler.supabase.com:"
        "5432/postgres?sslmode=require"
    )

    assert url.drivername == "postgresql+asyncpg"
    assert url.query["ssl"] == "require"
    assert "sslmode" not in url.query
    assert kwargs == {
        "pool_size": 2,
        "max_overflow": 0,
        "pool_timeout": 3,
        "pool_recycle": 300,
        "connect_args": {"timeout": 3, "command_timeout": 5},
    }


def test_supabase_transaction_pooler_disables_client_pool_and_statement_caches():
    url, kwargs = _engine_config(
        "postgresql://user:pass@aws-1-ap-south-1.pooler.supabase.com:"
        "6543/postgres?sslmode=require"
    )

    assert url.query["prepared_statement_cache_size"] == "0"
    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"] == {
        "statement_cache_size": 0,
        "timeout": 3,
        "command_timeout": 5,
    }


def test_existing_asyncpg_database_url_remains_supported():
    url, kwargs = _engine_config(
        "postgresql+asyncpg://user:pass@example.invalid/postgres"
    )

    assert url.drivername == "postgresql+asyncpg"
    assert kwargs == {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 3,
        "pool_recycle": 300,
        "connect_args": {"timeout": 3, "command_timeout": 5},
    }
