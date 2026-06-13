"""Regression guards for bug-bounty round 5 (iteration 2).

G5: a doctor-role staff login must bind to a Doctor row (no orphan accounts).
G6: staff/doctor logins enforce the same password strength as owner signup.
G8: at most one default doctor per branch — promoting one demotes the rest.
G17: over-long walk-in free-text is a clean 422, not a DB 500.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import Branch, Doctor, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _owner_jwt(org_id: str, branch_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@r5.test", "role": "org_admin",
            "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="R5 Org", owner_phone="+919000888001",
        owner_email=f"r5-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="R5 Branch",
        whatsapp_number=f"+9177{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(branch)
    await db.commit()
    return {"org_id": str(org.id), "branch_id": str(branch.id)}


async def test_staff_weak_password_rejected(clinic, client):
    """G6: an all-numeric / weak password is refused at staff creation."""
    bid = clinic["branch_id"]
    owner = _owner_jwt(clinic["org_id"], bid)
    r = await client.post(
        f"/branches/{bid}/staff", headers=_auth(owner),
        json={"name": "Weak", "email": f"w-{uuid.uuid4().hex[:6]}@d.test",
              "password": "12345678", "role": "receptionist"},
    )
    assert r.status_code == 422, r.text


async def test_doctor_role_login_without_match_rejected(clinic, client):
    """G5: a doctor-role login with no Doctor to bind to is refused (no orphan)."""
    bid = clinic["branch_id"]
    owner = _owner_jwt(clinic["org_id"], bid)
    r = await client.post(
        f"/branches/{bid}/staff", headers=_auth(owner),
        json={"name": "Dr Ghost", "email": f"ghost-{uuid.uuid4().hex[:6]}@d.test",
              "password": "GoodPass123", "role": "doctor"},
    )
    assert r.status_code == 422, r.text


async def test_doctor_role_login_links_to_doctor(clinic, client, db):
    """G5: a doctor-role login auto-binds to the Doctor invited with that email."""
    bid = clinic["branch_id"]
    owner = _owner_jwt(clinic["org_id"], bid)
    email = f"asha-{uuid.uuid4().hex[:6]}@d.test"
    dr = await client.post(
        f"/doctors/{bid}", headers=_auth(owner),
        json={"name": "Dr Asha", "specialization": "dentist",
              "routing_keywords": ["tooth"], "booking_type": "token",
              "daily_token_limit": 20, "invited_email": email},
    )
    assert dr.status_code in (200, 201), dr.text
    doctor_id = uuid.UUID(dr.json()["id"])

    st = await client.post(
        f"/branches/{bid}/staff", headers=_auth(owner),
        json={"name": "Dr Asha", "email": email, "password": "GoodPass123",
              "role": "doctor"},
    )
    assert st.status_code == 201, st.text
    linked_user = st.json()["user_id"]

    doc = (
        await db.execute(select(Doctor).where(Doctor.id == doctor_id))
    ).scalar_one()
    assert str(doc.user_id) == linked_user  # the login is bound to the Doctor row


async def test_single_default_doctor_per_branch(clinic, client, db):
    """G8: creating a second default doctor demotes the first."""
    bid = clinic["branch_id"]
    owner = _owner_jwt(clinic["org_id"], bid)
    d1 = await client.post(
        f"/doctors/{bid}", headers=_auth(owner),
        json={"name": "Dr One", "specialization": "dentist", "routing_keywords": ["a"],
              "booking_type": "token", "daily_token_limit": 20, "is_default_doctor": True},
    )
    assert d1.status_code in (200, 201)
    id1 = uuid.UUID(d1.json()["id"])

    d2 = await client.post(
        f"/doctors/{bid}", headers=_auth(owner),
        json={"name": "Dr Two", "specialization": "skin", "routing_keywords": ["b"],
              "booking_type": "token", "daily_token_limit": 20, "is_default_doctor": True},
    )
    assert d2.status_code in (200, 201)

    defaults = (
        await db.execute(
            select(Doctor).where(
                Doctor.branch_id == uuid.UUID(bid), Doctor.is_default_doctor.is_(True)
            )
        )
    ).scalars().all()
    assert len(defaults) == 1  # exactly one default survives
    assert defaults[0].id != id1  # the newest promotion won


async def test_walkin_overlong_name_is_422(clinic, client):
    """G17: an over-long patient name is a validation error, not a 500."""
    bid = clinic["branch_id"]
    owner = _owner_jwt(clinic["org_id"], bid)
    r = await client.post(
        f"/queue/{bid}/walkin", headers=_auth(owner),
        json={"doctor_id": str(uuid.uuid4()), "patient_name": "x" * 500},
    )
    assert r.status_code == 422, r.text
