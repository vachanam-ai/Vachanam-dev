"""RBAC tests: super_admin (Vinay) locked OUT of clinic PII routes.

DPDP Act 2023 boundary enforcement:
  - Vachanam is Data Processor. Vinay is platform admin.
  - Clinics are Data Fiduciary. Vinay MUST NOT access clinic patient/doctor PII.
  - Only /admin/* aggregate routes are allowed for super_admin.

Per sub-spec A section 5.4: assert_branch_access raises 403 for super_admin
on any branch-scoped route. Per section 5.6: forbid_admin raises 403 on
PII routes that don't use branch_id.

Test matrix:
  1. super_admin -> 403 on GET /queue/{branch_id}/today (branch-scoped PII)
  2. super_admin -> 403 on GET /doctors/{branch_id} (branch-scoped PII)
     NOTE: /doctors router not yet mounted (Task 8). Test targets /queue only.
     TODO(Task 8): add test for /doctors/{branch_id} once router is mounted.
  3. super_admin -> 200 on GET /admin/ping (admin aggregate route)

Per tester.md rule 1: tests written FIRST.
Per tester.md rule 5: no hardcoded secrets.
Per tester.md rule 7: negative tests for every error path.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt

from backend.config import settings
from backend.models.schema import Organization, Branch


# ======================================================================
# Test infrastructure
# ======================================================================


def _make_jwt(
    user_id: str | None = None,
    role: str = "super_admin",
    is_admin: bool = True,
    org_id: str | None = None,
    branch_ids: list[str] | None = None,
    expired: bool = False,
) -> str:
    """Mint a Vachanam-signed JWT for RBAC lockout tests."""
    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": "vinay-test@vachanam.in",
        "role": role,
        "org_id": org_id or str(uuid.uuid4()),
        "branch_ids": branch_ids or [],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def client(redis):
    """ASGI httpx client. Depends on redis for rate limiter init."""
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_branch(db):
    """Create a real org + branch in the test DB so assert_branch_access can
    look up the branch's org_id via the DB query."""
    org_id = uuid.uuid4()
    org = Organization(
        id=org_id,
        name="Test Clinic Org",
        owner_phone="+919999900001",
        owner_email="owner-lockout@test.com",
        plan="solo",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch_id = uuid.uuid4()
    branch = Branch(
        id=branch_id,
        org_id=org_id,
        name="Test Branch",
        whatsapp_number="+919999900002",
        status="active",
    )
    db.add(branch)
    await db.commit()
    return str(branch_id), str(org_id)


# ======================================================================
# Test 1: super_admin blocked on GET /queue/{branch_id}/today
# ======================================================================


@pytest.mark.asyncio
async def test_super_admin_blocked_on_queue(client, seeded_branch):
    """super_admin hitting a clinic PII route must get 403 with a message
    directing them to /admin endpoints.

    This enforces the DPDP boundary: Vinay (Data Processor admin) cannot
    access patient queue data that belongs to clinics (Data Fiduciary).
    """
    branch_id, _ = seeded_branch
    token = _make_jwt(role="super_admin", is_admin=True)
    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"super_admin on /queue/{{branch_id}}/today must return 403. "
        f"Got {r.status_code}: {r.text}"
    )
    detail = r.json().get("detail", "").lower()
    assert "/admin" in detail, (
        f"403 response must mention /admin endpoints as the alternative. "
        f"Got detail: {r.json().get('detail')!r}"
    )


# ======================================================================
# Test 2: super_admin blocked on PATCH /queue/{branch_id}/token/{id}/attend
# ======================================================================


@pytest.mark.asyncio
async def test_super_admin_blocked_on_token_attend(client, seeded_branch):
    """super_admin must not be able to mark patients as attended.
    This is a write operation on clinic PII — doubly prohibited."""
    branch_id, _ = seeded_branch
    token = _make_jwt(role="super_admin", is_admin=True)
    fake_token_id = str(uuid.uuid4())
    r = await client.patch(
        f"/queue/{branch_id}/token/{fake_token_id}/attend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"super_admin on token attend must return 403. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 3: super_admin allowed on GET /admin/ping
# ======================================================================


@pytest.mark.asyncio
async def test_super_admin_allowed_on_admin_ping(client):
    """super_admin must be able to access /admin/* routes.
    These are aggregate routes designed for the platform admin."""
    token = _make_jwt(role="super_admin", is_admin=True)
    r = await client.get(
        "/admin/ping",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, (
        f"super_admin on /admin/ping must return 200. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 4: is_admin=True with role!=super_admin also blocked
# ======================================================================


@pytest.mark.asyncio
async def test_is_admin_true_also_blocked_on_queue(client, seeded_branch):
    """Even if someone has is_admin=True but a different role, they should
    still be blocked on clinic PII routes by assert_branch_access."""
    branch_id, _ = seeded_branch
    # is_admin=True with role=org_admin (unusual but possible in edge cases)
    token = _make_jwt(role="org_admin", is_admin=True, org_id=str(uuid.uuid4()))
    r = await client.get(
        f"/queue/{branch_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    # is_admin=True triggers the super_admin block in assert_branch_access
    assert r.status_code == 403, (
        f"is_admin=True user on clinic PII route must return 403. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 5: super_admin on non-existent branch also 403 (not 404)
# ======================================================================


@pytest.mark.asyncio
async def test_super_admin_fake_branch_returns_403(client):
    """super_admin should get 403 even on a non-existent branch_id.
    The super_admin check fires BEFORE the branch lookup."""
    fake_branch = str(uuid.uuid4())
    token = _make_jwt(role="super_admin", is_admin=True)
    r = await client.get(
        f"/queue/{fake_branch}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"super_admin on non-existent branch must still return 403 (not 404). "
        f"Got {r.status_code}: {r.text}"
    )
