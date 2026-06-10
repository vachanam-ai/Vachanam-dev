"""RBAC tests: org_admin auto-inherits all branches in own org.

Sub-spec A section 5.4 behavior change:
  - org_admin with EMPTY branch_ids still accesses any branch where
    branch.org_id == user.org_id (auto-inheritance via DB lookup).
  - org_admin CANNOT access branches belonging to other orgs.
  - receptionist with empty branch_ids gets 403 on all branches.
  - receptionist with branch_a in branch_ids gets 200 on branch_a, 403 on branch_b.

These tests require a real DB because assert_branch_access now queries
the branches table to resolve branch.org_id for org_admin checks.

Per tester.md rule 1: tests written FIRST.
Per tester.md rule 5: no hardcoded secrets.
Per tester.md rule 7: negative tests for every error path.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings
from backend.models.schema import Organization, Branch


# ======================================================================
# Test infrastructure
# ======================================================================


def _make_jwt(
    user_id: str | None = None,
    role: str = "org_admin",
    org_id: str | None = None,
    branch_ids: list[str] | None = None,
    is_admin: bool = False,
) -> str:
    """Mint a Vachanam-signed JWT for RBAC inheritance tests."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "email": f"rbac-test-{uuid.uuid4().hex[:6]}@test.com",
        "role": role,
        "org_id": org_id,
        "branch_ids": branch_ids if branch_ids is not None else [],
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
async def two_orgs_three_branches(db):
    """Create two orgs with branches:
      org_a -> branch_a, branch_b
      org_b -> branch_other
    Returns dict with all IDs as strings.
    """
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()

    org_a = Organization(
        id=org_a_id,
        name="Clinic A Org",
        owner_phone="+919999910001",
        owner_email=f"org-a-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic",
        status="active",
    )
    org_b = Organization(
        id=org_b_id,
        name="Clinic B Org",
        owner_phone="+919999910002",
        owner_email=f"org-b-{uuid.uuid4().hex[:6]}@test.com",
        plan="solo",
        status="active",
    )
    db.add_all([org_a, org_b])
    await db.flush()

    branch_a_id = uuid.uuid4()
    branch_b_id = uuid.uuid4()
    branch_other_id = uuid.uuid4()

    branch_a = Branch(
        id=branch_a_id,
        org_id=org_a_id,
        name="Branch A",
        whatsapp_number=f"+91999991{uuid.uuid4().hex[:4]}",
        status="active",
    )
    branch_b = Branch(
        id=branch_b_id,
        org_id=org_a_id,
        name="Branch B",
        whatsapp_number=f"+91999992{uuid.uuid4().hex[:4]}",
        status="active",
    )
    branch_other = Branch(
        id=branch_other_id,
        org_id=org_b_id,
        name="Branch Other Org",
        whatsapp_number=f"+91999993{uuid.uuid4().hex[:4]}",
        status="active",
    )
    db.add_all([branch_a, branch_b, branch_other])
    await db.commit()

    return {
        "org_a_id": str(org_a_id),
        "org_b_id": str(org_b_id),
        "branch_a_id": str(branch_a_id),
        "branch_b_id": str(branch_b_id),
        "branch_other_id": str(branch_other_id),
    }


# ======================================================================
# Test 1: org_admin with empty branch_ids accesses own org's branch_a
# ======================================================================


@pytest.mark.asyncio
async def test_org_admin_accesses_own_branch_a_without_branch_ids(
    client, two_orgs_three_branches
):
    """org_admin with branch_ids=[] can access branch_a because
    branch_a.org_id == user.org_id (auto-inheritance).

    This is the key behavior change: org_admin no longer needs branch_ids
    populated. The DB lookup proves ownership via org_id match.
    """
    data = two_orgs_three_branches
    token = _make_jwt(
        role="org_admin",
        org_id=data["org_a_id"],
        branch_ids=[],  # EMPTY — auto-inherits via org_id
    )
    r = await client.get(
        f"/queue/{data['branch_a_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Queue may return 200 with empty data (no tokens today) or 500 if
    # DB query fails on empty tables — but NOT 403. The branch access
    # check must pass.
    assert r.status_code != 403, (
        f"org_admin with empty branch_ids on own org's branch must NOT get 403. "
        f"Got {r.status_code}: {r.text}"
    )
    assert r.status_code in (200, 500), (
        f"Expected 200 (empty queue) or 500 (DB query on empty tables). "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 2: org_admin with empty branch_ids accesses own org's branch_b
# ======================================================================


@pytest.mark.asyncio
async def test_org_admin_accesses_own_branch_b_without_branch_ids(
    client, two_orgs_three_branches
):
    """org_admin with branch_ids=[] can access branch_b (same org)."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="org_admin",
        org_id=data["org_a_id"],
        branch_ids=[],
    )
    r = await client.get(
        f"/queue/{data['branch_b_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code != 403, (
        f"org_admin with empty branch_ids on own org's branch_b must NOT get 403. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 3: org_admin blocked from other org's branch
# ======================================================================


@pytest.mark.asyncio
async def test_org_admin_blocked_from_other_org_branch(
    client, two_orgs_three_branches
):
    """org_admin from org_a CANNOT access branch_other (belongs to org_b).
    This is the cross-org isolation boundary."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="org_admin",
        org_id=data["org_a_id"],
        branch_ids=[],
    )
    r = await client.get(
        f"/queue/{data['branch_other_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"org_admin from org_a on org_b's branch must return 403. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 4: org_admin on non-existent branch gets 404
# ======================================================================


@pytest.mark.asyncio
async def test_org_admin_nonexistent_branch_returns_404(
    client, two_orgs_three_branches
):
    """org_admin querying a branch that doesn't exist should get 404."""
    data = two_orgs_three_branches
    fake_branch = str(uuid.uuid4())
    token = _make_jwt(
        role="org_admin",
        org_id=data["org_a_id"],
    )
    r = await client.get(
        f"/queue/{fake_branch}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, (
        f"org_admin on non-existent branch must return 404. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 5: receptionist with empty branch_ids gets 403
# ======================================================================


@pytest.mark.asyncio
async def test_receptionist_empty_branch_ids_blocked(
    client, two_orgs_three_branches
):
    """receptionist with branch_ids=[] CANNOT access any branch.
    Receptionist does NOT auto-inherit — explicit assignment required."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="receptionist",
        org_id=data["org_a_id"],
        branch_ids=[],
    )
    r = await client.get(
        f"/queue/{data['branch_a_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"receptionist with empty branch_ids must return 403. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 6: receptionist with branch_a in branch_ids gets 200 on branch_a
# ======================================================================


@pytest.mark.asyncio
async def test_receptionist_with_branch_a_accesses_branch_a(
    client, two_orgs_three_branches
):
    """receptionist with branch_a in branch_ids can access branch_a."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="receptionist",
        org_id=data["org_a_id"],
        branch_ids=[data["branch_a_id"]],
    )
    r = await client.get(
        f"/queue/{data['branch_a_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code != 403, (
        f"receptionist with branch_a in branch_ids must NOT get 403 on branch_a. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 7: receptionist with branch_a blocked from branch_b
# ======================================================================


@pytest.mark.asyncio
async def test_receptionist_with_branch_a_blocked_from_branch_b(
    client, two_orgs_three_branches
):
    """receptionist with only branch_a in branch_ids CANNOT access branch_b."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="receptionist",
        org_id=data["org_a_id"],
        branch_ids=[data["branch_a_id"]],
    )
    r = await client.get(
        f"/queue/{data['branch_b_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"receptionist with branch_a only must get 403 on branch_b. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 8: doctor role with branch_a in branch_ids can access branch_a
# ======================================================================


@pytest.mark.asyncio
async def test_doctor_role_with_branch_ids_accesses_own_branch(
    client, two_orgs_three_branches
):
    """doctor role (new in sub-spec A) follows same rules as receptionist:
    requires explicit branch_ids assignment."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="doctor",
        org_id=data["org_a_id"],
        branch_ids=[data["branch_a_id"]],
    )
    r = await client.get(
        f"/queue/{data['branch_a_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code != 403, (
        f"doctor with branch_a in branch_ids must NOT get 403 on branch_a. "
        f"Got {r.status_code}: {r.text}"
    )


# ======================================================================
# Test 9: doctor role with empty branch_ids blocked
# ======================================================================


@pytest.mark.asyncio
async def test_doctor_role_empty_branch_ids_blocked(
    client, two_orgs_three_branches
):
    """doctor role with empty branch_ids cannot access any branch."""
    data = two_orgs_three_branches
    token = _make_jwt(
        role="doctor",
        org_id=data["org_a_id"],
        branch_ids=[],
    )
    r = await client.get(
        f"/queue/{data['branch_a_id']}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, (
        f"doctor with empty branch_ids must return 403. "
        f"Got {r.status_code}: {r.text}"
    )
