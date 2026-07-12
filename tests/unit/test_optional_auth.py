"""optional_current_user: valid Bearer → user, everything else → None (no 401)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import jwt

from backend.config import settings

pytestmark = pytest.mark.asyncio


class _Req:
    def __init__(self, auth=None):
        self.headers = {"Authorization": auth} if auth else {}


def _tok(**over):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()), "email": "u@t.com", "role": "org_admin",
        "org_id": str(uuid.uuid4()), "branch_ids": [], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }
    payload.update(over)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def test_optional_auth_returns_user_for_valid_token():
    from backend.middleware.auth_middleware import optional_current_user
    u = await optional_current_user(_Req(f"Bearer {_tok()}"))
    assert u is not None and u.role == "org_admin"


async def test_optional_auth_returns_none_for_missing_or_garbage():
    from backend.middleware.auth_middleware import optional_current_user
    assert await optional_current_user(_Req(None)) is None
    assert await optional_current_user(_Req("Bearer garbage")) is None
