"""DPDP self-serve deletion (Vinay 2026-07-17): owner removes staff logins and
can erase the whole clinic. Destructive paths must be re-authenticated and
tenant-scoped (RULE 1)."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import Branch, Doctor, Organization, Patient, User

_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _jwt(role, org_id, branch_id, user_id):
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(user_id), "email": f"{role}@t.test", "role": role,
        "org_id": str(org_id), "branch_ids": [str(branch_id)], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }, settings.jwt_secret, algorithm=_ALGO)


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _seed(db, password="Own3r@Pass!"):
    from backend.routers.auth import _hash_password

    org = Organization(name="DelOrg", owner_phone="+919000700094",
                       owner_email=f"del-{uuid.uuid4().hex[:6]}@test.com",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    b = Branch(org_id=org.id, name="DelBranch",
               whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active")
    db.add(b)
    await db.flush()
    owner = User(id=uuid.uuid4(), org_id=org.id, email=f"own-{uuid.uuid4().hex[:6]}@t.test",
                 role="org_admin", branch_ids=[str(b.id)],
                 password_hash=_hash_password(password) if password else None)
    staffu = User(id=uuid.uuid4(), org_id=org.id, email=f"st-{uuid.uuid4().hex[:6]}@t.test",
                  role="doctor", branch_ids=[str(b.id)])
    db.add_all([owner, staffu])
    await db.flush()
    doc = Doctor(branch_id=b.id, name="Dr Linked", booking_type="token",
                 user_id=staffu.id, status="active")
    pat = Patient(branch_id=b.id, name="P", phone=f"+9190{str(uuid.uuid4().int)[:8]}")
    db.add_all([doc, pat])
    await db.commit()
    return org, b, owner, staffu, doc


@pytest.mark.asyncio
async def test_owner_removes_staff_login_doctor_unlinked_records_stay(client, db):
    org, b, owner, staffu, doc = await _seed(db)
    staff_id, doc_id, owner_id, b_id = staffu.id, doc.id, owner.id, b.id
    tok = _jwt("org_admin", org.id, b_id, owner_id)

    r = await client.delete(f"/branches/{b_id}/staff/{staff_id}", headers=_auth(tok))
    assert r.status_code == 200, r.text

    db.expire_all()  # endpoint wrote via its own session — drop cached state
    assert (await db.execute(select(User).where(User.id == staff_id))).scalar_one_or_none() is None
    d = (await db.execute(select(Doctor).where(Doctor.id == doc_id))).scalar_one()
    assert d.user_id is None  # login gone, doctor record STAYS

    # Cannot remove self.
    r2 = await client.delete(f"/branches/{b_id}/staff/{owner_id}", headers=_auth(tok))
    assert r2.status_code == 422

    # Cross-org target -> 404 (RULE 1).
    org2, b2, owner2, staffu2, _ = await _seed(db)
    r3 = await client.delete(f"/branches/{b_id}/staff/{staffu2.id}", headers=_auth(tok))
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_delete_clinic_requires_password_then_erases_everything(client, db):
    org, b, owner, staffu, doc = await _seed(db, password="Own3r@Pass!")
    tok = _jwt("org_admin", org.id, b.id, owner.id)

    # Wrong password -> 401, nothing deleted.
    r = await client.post("/auth/delete-account", headers=_auth(tok),
                          json={"password": "wrong"})
    assert r.status_code == 401
    assert (await db.execute(select(Organization).where(Organization.id == org.id))).scalar_one_or_none() is not None

    # Correct password -> org + branches + users + patients + doctors all gone.
    r2 = await client.post("/auth/delete-account", headers=_auth(tok),
                           json={"password": "Own3r@Pass!"})
    assert r2.status_code == 200, r2.text
    for model, cond in [
        (Organization, Organization.id == org.id),
        (Branch, Branch.org_id == org.id),
        (User, User.org_id == org.id),
        (Doctor, Doctor.branch_id == b.id),
        (Patient, Patient.branch_id == b.id),
    ]:
        left = (await db.execute(select(model).where(cond))).scalars().all()
        assert left == [], f"{model.__name__} rows survived erasure"


@pytest.mark.asyncio
async def test_delete_clinic_staff_forbidden_and_google_needs_DELETE(client, db, monkeypatch):
    org, b, owner, staffu, doc = await _seed(db, password=None)  # Google-only owner
    org_id, owner_email = org.id, owner.email  # capture before commit expiry
    staff_tok = _jwt("doctor", org.id, b.id, staffu.id)
    r = await client.post("/auth/delete-account", headers=_auth(staff_tok),
                          json={"confirm": "DELETE"})
    assert r.status_code == 403  # only the owner

    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client-id")
    own_tok = _jwt("org_admin", org.id, b.id, owner.id)
    r2 = await client.post("/auth/delete-account", headers=_auth(own_tok), json={})
    assert r2.status_code == 422  # must type DELETE

    # SEC (d133c40): typing DELETE is only a UI guard — a Google-only owner must
    # ALSO re-verify a FRESH Google ID token, so a stolen session cannot destroy
    # the clinic on its own. No token -> 401.
    r3 = await client.post("/auth/delete-account", headers=_auth(own_tok),
                           json={"confirm": "delete"})
    assert r3.status_code == 401  # reauth required

    # A token for a DIFFERENT Google account is rejected (email must match).
    monkeypatch.setattr("backend.routers.auth.google_id_token.verify_oauth2_token",
                        lambda *a, **k: {"email": "attacker@t.test"})
    r4 = await client.post("/auth/delete-account", headers=_auth(own_tok),
                           json={"confirm": "DELETE", "id_token": "x"})
    assert r4.status_code == 401

    # Fresh Google ID token matching the owner email -> erases the clinic.
    monkeypatch.setattr("backend.routers.auth.google_id_token.verify_oauth2_token",
                        lambda *a, **k: {"email": owner_email})
    r5 = await client.post("/auth/delete-account", headers=_auth(own_tok),
                           json={"confirm": "delete", "id_token": "good"})
    assert r5.status_code == 200, r5.text
    assert (await db.execute(
        select(Organization).where(Organization.id == org_id))).scalar_one_or_none() is None
