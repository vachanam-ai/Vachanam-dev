import pytest

from scripts.migrate_postgres_data import _postgres_url, migrate


def test_migration_url_preserves_encoded_password_and_requires_tls():
    result = _postgres_url(
        "postgresql+asyncpg://user:p%40ss@example.invalid/postgres"
    )

    assert result.startswith("postgresql://")
    assert "p%40ss" in result
    assert result.endswith("?sslmode=require")


def test_migration_refuses_same_source_and_target_before_connecting():
    url = "postgresql://user:pass@localhost/postgres"

    with pytest.raises(RuntimeError, match="same database"):
        migrate(url, url)
