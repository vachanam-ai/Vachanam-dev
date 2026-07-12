"""Integration tests for the Patient Information router (Task 5).

Covers:
  - test_list_returns_last_doctor — GET returns each patient's most-recent
    token's doctor name (window-function, no N+1); null when no token.
  - test_patch_edits_name_age — PATCH updates name + age, returns the new values.
  - test_patch_duplicate_collides_409 — renaming a family member onto an
    existing (phone, lower(name)) sibling → 409 duplicate_patient (RULE: the
    partial unique index uq_patient_branch_phone_name).
  - test_patch_cross_branch_404 — a user scoped to their own branch cannot edit
    a patient in another branch (RULE 1 tenant isolation).

Fixtures: the integration suite exposes only `db` (and `redis`) from conftest —
there are no `client`/`org_admin_headers`/`branch`/`doctor`/`other_branch`
fixtures, so (matching test_treatment_notes_api.py) each test seeds its own
Organization/User/Branch/Doctor/Patient rows and drives auth by overriding
get_current_user. The brief's fixture names were illustrative.

Schema NOT NULL fields honoured:
  - Branch.org_id (RESTRICT FK) + Branch.whatsapp_number (NOT NULL, unique).
  - Doctor.booking_type NOT NULL ("token").
  - Token.source NOT NULL ("voice"), Token.status default "confirmed".
  - CurrentUser needs a jti.
"""
import uuid
import datetime

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.middleware.auth_middleware import get_current_user, CurrentUser
from backend.models.schema import Branch, Doctor, Patient, Organization, Token


def _as_user(branch_id, org_id, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="d@c.com", role=role,
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


def _org(org_id):
    return Organization(id=org_id, name="Org", owner_phone="+919000099001",
                        owner_email=f"owner-{org_id}@c.com", plan="clinic")


async def _seed_branch(db, whatsapp_number):
    org_id = uuid.uuid4()
    db.add(_org(org_id))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number=whatsapp_number)
    db.add(br)
    await db.flush()
    return org_id, br


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_list_returns_last_doctor(db):
    org_id, br = await _seed_branch(db, "+910000000050")
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi",
                phone="+919000000020", age=30, is_primary=True)
    db.add_all([doc, p])
    await db.flush()
    db.add(Token(id=uuid.uuid4(), branch_id=br.id, doctor_id=doc.id,
                 patient_id=p.id, date=datetime.date.today(), token_number=1,
                 status="confirmed", source="voice"))
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.get(f"/patients/branches/{br.id}/patients")
            assert r.status_code == 200, r.text
            row = next(x for x in r.json()["patients"] if x["id"] == str(p.id))
            assert row["last_doctor"] == doc.name
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_null_doctor_and_sorted(db):
    org_id, br = await _seed_branch(db, "+910000000051")
    # No token for either patient -> last_doctor null. Names out of order to
    # verify the response is sorted by lower(name): "amar" before "Zoya".
    z = Patient(id=uuid.uuid4(), branch_id=br.id, name="Zoya",
                phone="+919000000030", is_primary=True)
    a = Patient(id=uuid.uuid4(), branch_id=br.id, name="amar",
                phone="+919000000031", is_primary=True)
    db.add_all([z, a])
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.get(f"/patients/branches/{br.id}/patients")
            assert r.status_code == 200, r.text
            names = [x["name"] for x in r.json()["patients"]]
            assert names == ["amar", "Zoya"]
            assert all(x["last_doctor"] is None for x in r.json()["patients"])
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_edits_name_age(db):
    org_id, br = await _seed_branch(db, "+910000000052")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Old",
                phone="+919000000021", age=20, is_primary=True)
    db.add(p)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.patch(f"/patients/{p.id}",
                               json={"branch_id": str(br.id), "name": "New", "age": 21})
            assert r.status_code == 200, r.text
            assert r.json()["name"] == "New" and r.json()["age"] == 21
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_b13_patch_whitespace_only_name_rejected(db):
    """B13: a whitespace-only name passes min_length=1 but strips to "" — it must
    be rejected 422, never saved as an empty name."""
    org_id, br = await _seed_branch(db, "+910000000058")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Real",
                phone="+919000000028", age=30, is_primary=True)
    db.add(p)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.patch(f"/patients/{p.id}",
                               json={"branch_id": str(br.id), "name": "   "})
            assert r.status_code == 422, r.text
    finally:
        app.dependency_overrides.clear()

    # the name is unchanged in the DB
    import backend.database as _dbmod
    from sqlalchemy import select as _select

    async with _dbmod.AsyncSessionLocal() as s:
        got = (await s.execute(_select(Patient).where(Patient.id == p.id))).scalar_one()
    assert got.name == "Real"


@pytest.mark.asyncio
async def test_patch_duplicate_collides_409(db):
    org_id, br = await _seed_branch(db, "+910000000053")
    a = Patient(id=uuid.uuid4(), branch_id=br.id, name="Amma",
                phone="+919000000022", is_primary=True)
    b = Patient(id=uuid.uuid4(), branch_id=br.id, name="Nanna",
                phone="+919000000022", is_primary=False)
    db.add_all([a, b])
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            # Rename Nanna -> Amma on the same phone: collides with a.
            r = await ac.patch(f"/patients/{b.id}",
                               json={"branch_id": str(br.id), "name": "Amma"})
            assert r.status_code == 409, r.text
            assert r.json()["detail"] == "duplicate_patient"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_phone_move_becomes_primary(db):
    """Moving a patient to a fresh phone that has no owner makes them the
    primary of the new phone (is_primary re-evaluated on phone change)."""
    org_id, br = await _seed_branch(db, "+910000000054")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Kiran",
                phone="+919000000040", is_primary=False)
    db.add(p)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.patch(f"/patients/{p.id}",
                               json={"branch_id": str(br.id), "phone": "9000000041"})
            assert r.status_code == 200, r.text
            assert r.json()["phone"] == "+919000000041"
            assert r.json()["is_primary"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_bad_phone_422(db):
    org_id, br = await _seed_branch(db, "+910000000055")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Bad",
                phone="+919000000042", is_primary=True)
    db.add(p)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.patch(f"/patients/{p.id}",
                               json={"branch_id": str(br.id), "phone": "12345"})
            assert r.status_code == 422, r.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_cross_branch_404(db):
    org_id, br = await _seed_branch(db, "+910000000056")
    _other_org, other = await _seed_branch(db, "+910000000057")
    p = Patient(id=uuid.uuid4(), branch_id=other.id, name="X", phone="+919000000023")
    db.add(p)
    await db.commit()

    # The user is scoped to `br`, not `other`. Claiming other's branch_id must be
    # denied by assert_branch_access (403); claiming br for a patient that isn't in
    # br yields 404. Either is an acceptable rejection.
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with _client() as ac:
            r = await ac.patch(f"/patients/{p.id}",
                               json={"branch_id": str(other.id), "name": "Y"})
            assert r.status_code in (403, 404), r.text
    finally:
        app.dependency_overrides.clear()
