import uuid
from unittest.mock import AsyncMock

import pytest

from backend.middleware.auth_middleware import CurrentUser
from backend.middleware.branch_guard import assert_branch_access


@pytest.mark.asyncio
async def test_signed_owner_branch_skips_redundant_database_lookup():
    branch_id = str(uuid.uuid4())
    user = CurrentUser(
        user_id=str(uuid.uuid4()),
        email="owner@example.test",
        role="org_admin",
        org_id=str(uuid.uuid4()),
        branch_ids=[branch_id],
        is_admin=False,
        jti="test-jti",
    )
    db = AsyncMock()

    await assert_branch_access(user, branch_id, db)

    db.execute.assert_not_awaited()
