from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from backend.config import settings
from backend.middleware import auth_middleware as auth


@pytest.mark.asyncio
async def test_recently_validated_session_skips_database(monkeypatch):
    user_id = uuid.uuid4()
    auth.cache_active_user_version(SimpleNamespace(id=user_id, token_version=3))

    class Redis:
        async def exists(self, *_keys):
            return 0

    class DatabaseMustNotOpen:
        def __call__(self):
            raise AssertionError("hot auth path opened the database")

    monkeypatch.setattr(auth, "_revocation_redis", lambda: Redis())
    monkeypatch.setattr(auth, "AsyncSessionLocal", DatabaseMustNotOpen())
    now = datetime.now(timezone.utc)
    token = jwt.encode({
        "sub": str(user_id), "email": "owner@example.test", "role": "org_admin",
        "org_id": str(uuid.uuid4()), "branch_ids": [], "is_admin": False,
        "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": str(uuid.uuid4()), "tv": 3,
    }, settings.jwt_secret, algorithm="HS256")

    current = await auth.get_current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )
    assert current.user_id == str(user_id)
