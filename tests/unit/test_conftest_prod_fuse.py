"""FIXLOG #324 regression: the test process must be physically unable to reach
the real DATABASE_URL. Before the conftest fuse, any test that used an app
client without the `db` fixture silently wrote to PROD (junk support tickets
appeared on the live desk after every suite run)."""
import pytest

import backend.database as dbm
from backend.config import settings

def test_settings_database_url_is_fused_to_test_db():
    assert settings.database_url == settings.test_database_url
    assert "neon.tech" not in settings.database_url
    assert "_test" in settings.database_url or "test_" in settings.database_url


def test_module_engine_points_at_test_db():
    url = str(dbm.engine.url)
    assert "neon.tech" not in url
    assert "_test" in url or "test_" in url


@pytest.mark.asyncio
async def test_get_db_sessions_bind_to_test_engine():
    """The exact leak path: a route's Depends(get_db) session, requested
    WITHOUT the db fixture, must still bind to the test database."""
    agen = dbm.get_db()
    session = await agen.__anext__()
    try:
        url = str(session.bind.url)
        assert "neon.tech" not in url
        assert "_test" in url or "test_" in url
    finally:
        await agen.aclose()
