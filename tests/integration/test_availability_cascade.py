"""Integration tests for /availability router + cascade_for_unavailability service.

Covers (Task 9 spec):
  test_post_unavailability_creates_rows_for_date_range
  test_post_unavailability_cascade_cancels_existing_tokens
  test_post_unavailability_creates_followup_tasks_for_cancelled
  test_post_unavailability_enqueues_cal_delete_for_slot_doctor_tokens
  test_post_unavailability_no_cal_enqueue_for_token_doctor_tokens
  test_post_unavailability_idempotent_on_overlap
  test_get_affected_returns_token_count_without_cancelling
  test_delete_single_date_removes_row
  test_receptionist_can_get_but_not_post
  test_cross_branch_403
  test_super_admin_blocked_403

All JWT tokens are hand-crafted from settings.jwt_secret — no real auth flow needed.
Uses httpx.AsyncClient + ASGITransport so the conftest `db` fixture's patched
AsyncSessionLocal is visible to router's Depends(get_db).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import pytest
import pytest_asyncio
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.schema import (
    Branch,
    CalendarWriteTask,
    Doctor,
    DoctorUnavailability,
    FollowupTask,
    Organization,
    Patient,
    Token,
)

_ALGO = "HS256"


# ---------------------------------------------------------------------------
# JWT factory helpers
# ---------------------------------------------------------------------------

def _make_jwt(
    *,
    user_id: str,
    email: str,
    role: str,
    org_id: Optional[str] = None,
    branch_ids: Optional[list[str]] = None,
    is_admin: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "org_id": org_id,
        "branch_ids": branch_ids or [],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(redis):
    """Async httpx client wired to the app via ASGITransport.

    The `redis` fixture ensures the rate-limiter Redis pool is initialised.
    Same event loop as db fixture so conftest-patched AsyncSessionLocal is
    visible in router dependencies.
    """
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# DB seed fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def clinic(db: AsyncSession):
    """Org A + Branch A."""
    org = Organization(
        name="Availability Test Clinic A",
        owner_phone="+919100000001",
        owner_email=f"avail-a-{uuid.uuid4()}@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Branch A",
        whatsapp_number=f"+91910{str(uuid.uuid4().int)[:7]}",
        status="active",
    )
    db.add(branch)
    await db.commit()

    return {"org_id": str(org.id), "branch_id": str(branch.id)}


@pytest_asyncio.fixture
async def clinic_b(db: AsyncSession):
    """Org B + Branch B — for cross-branch isolation tests."""
    org = Organization(
        name="Availability Test Clinic B",
        owner_phone="+919200000002",
        owner_email=f"avail-b-{uuid.uuid4()}@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Branch B",
        whatsapp_number=f"+91920{str(uuid.uuid4().int)[:7]}",
        status="active",
    )
    db.add(branch)
    await db.commit()

    return {"org_id": str(org.id), "branch_id": str(branch.id)}


@pytest_asyncio.fixture
async def org_admin_jwt(clinic):
    return _make_jwt(
        user_id=str(uuid.uuid4()),
        email="avail-admin@test.com",
        role="org_admin",
        org_id=clinic["org_id"],
        branch_ids=[clinic["branch_id"]],
    )


@pytest_asyncio.fixture
async def receptionist_jwt(clinic):
    return _make_jwt(
        user_id=str(uuid.uuid4()),
        email="avail-recep@test.com",
        role="receptionist",
        org_id=clinic["org_id"],
        branch_ids=[clinic["branch_id"]],
    )


@pytest_asyncio.fixture
async def super_admin_jwt():
    return _make_jwt(
        user_id=str(uuid.uuid4()),
        email="vinay@vachanam.in",
        role="super_admin",
        is_admin=True,
    )


async def _seed_doctor(
    db: AsyncSession,
    branch_id: str,
    *,
    booking_type: str = "token",
    name: str = "Dr Test",
    google_calendar_id: Optional[str] = None,
) -> Doctor:
    doc = Doctor(
        branch_id=uuid.UUID(branch_id),
        name=name,
        booking_type=booking_type,
        available_weekdays=[0, 1, 2, 3, 4, 5, 6],
        pre_appointment_reminder=(booking_type == "appointment"),
        post_treatment_followup=(booking_type == "appointment"),
        status="active",
        google_calendar_id=google_calendar_id,
    )
    db.add(doc)
    await db.commit()
    return doc


async def _seed_patient(db: AsyncSession, branch_id: str, *, name: str = "Patient One", phone: str = "+919999900001") -> Patient:
    patient = Patient(
        branch_id=uuid.UUID(branch_id),
        name=name,
        phone=phone,
        followup_consent=True,
    )
    db.add(patient)
    await db.commit()
    return patient


async def _seed_token(
    db: AsyncSession,
    branch_id: str,
    doctor: Doctor,
    patient: Patient,
    *,
    on_date: date,
    status: str = "confirmed",
    token_number: int = 1,
    google_calendar_event_id: Optional[str] = None,
) -> Token:
    tok = Token(
        branch_id=uuid.UUID(branch_id),
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=on_date,
        token_number=token_number,
        source="walk_in",
        status=status,
        google_calendar_event_id=google_calendar_event_id,
    )
    db.add(tok)
    await db.commit()
    return tok


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_unavailability_creates_rows_for_date_range(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """POST with 3-day range must create 3 DoctorUnavailability rows.

    Dates are RELATIVE to today — hardcoded 2026-07-01..03 rotted into 'past
    dates' the moment the calendar rolled past them (failed 2026-07-04)."""
    doctor = await _seed_doctor(db, clinic["branch_id"])
    from datetime import timedelta

    d1 = date.today() + timedelta(days=1)
    d3 = date.today() + timedelta(days=3)

    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={
            "date_from": d1.isoformat(),
            "date_to": d3.isoformat(),
            "reason": "Conference",
        },
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["unavailable_dates"] == 3

    # Verify rows exist in DB with correct branch_id scope (Rule 1)
    result = await db.execute(
        select(DoctorUnavailability).where(
            DoctorUnavailability.branch_id == uuid.UUID(clinic["branch_id"]),
            DoctorUnavailability.doctor_id == doctor.id,
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    dates_in_db = {r.date for r in rows}
    assert dates_in_db == {d1, d1 + timedelta(days=1), d3}


@pytest.mark.asyncio
async def test_b9_leave_range_starting_in_past_never_cancels_past_bookings(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """B9: marking leave with a range that STARTS in the past (but ends in the
    future) must NOT cancel yesterday's confirmed bookings (patients who came
    but were never marked attended) — only today onward."""
    from backend.routers.queue import _branch_today

    branch_uuid = uuid.UUID(clinic["branch_id"])
    branch_today = await _branch_today(branch_uuid, db)
    yesterday = branch_today - timedelta(days=1)
    tomorrow = branch_today + timedelta(days=1)

    doctor = await _seed_doctor(db, clinic["branch_id"])
    p_past = await _seed_patient(db, clinic["branch_id"], name="Past", phone="+919999911101")
    p_today = await _seed_patient(db, clinic["branch_id"], name="Today", phone="+919999911102")
    past_tok = await _seed_token(db, clinic["branch_id"], doctor, p_past,
                                 on_date=yesterday, token_number=1)
    today_tok = await _seed_token(db, clinic["branch_id"], doctor, p_today,
                                  on_date=branch_today, token_number=2)

    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": yesterday.isoformat(), "date_to": tomorrow.isoformat()},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    assert r.json()["cancelled_tokens"] == 1  # only today's, not yesterday's

    # Read the truth on a FRESH session (router committed on its own session).
    import backend.database as _dbmod

    async with _dbmod.AsyncSessionLocal() as s:
        past = (await s.execute(select(Token).where(Token.id == past_tok.id))).scalar_one()
        today = (await s.execute(select(Token).where(Token.id == today_tok.id))).scalar_one()
        ft_past = (await s.execute(
            select(FollowupTask).where(FollowupTask.patient_id == p_past.id)
        )).scalars().all()
    assert past.status == "confirmed", "past booking must be untouched"
    assert today.status == "cancelled_by_clinic"
    assert ft_past == [], "no rebook call may be scheduled about a past date"


@pytest.mark.asyncio
async def test_post_unavailability_cascade_cancels_existing_tokens(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """5 confirmed tokens in range must all become 'cancelled_by_clinic' after POST."""
    doctor = await _seed_doctor(db, clinic["branch_id"])

    token_ids = []
    for i in range(5):
        patient = await _seed_patient(
            db, clinic["branch_id"],
            name=f"Patient {i}",
            phone=f"+9199999{str(i).zfill(5)}",
        )
        on_date = date(2026, 8, 10 + i)
        tok = await _seed_token(
            db, clinic["branch_id"], doctor, patient,
            on_date=on_date, token_number=i + 1,
        )
        token_ids.append(tok.id)

    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2026-08-10", "date_to": "2026-08-14"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cancelled_tokens"] == 5

    # Verify each token is cancelled with cancelled_by_user_id set
    for tid in token_ids:
        result = await db.execute(
            select(Token).where(
                Token.id == tid,
                Token.branch_id == uuid.UUID(clinic["branch_id"]),  # Rule 1
            )
        )
        tok = result.scalar_one()
        assert tok.status == "cancelled_by_clinic", f"Token {tid} not cancelled"
        assert tok.cancelled_by_user_id is not None


@pytest.mark.asyncio
async def test_post_unavailability_creates_followup_tasks_for_cancelled(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """5 cancelled tokens must each produce a FollowupTask with task_type='cascade_rebook' and token_id set."""
    doctor = await _seed_doctor(db, clinic["branch_id"])

    token_ids = []
    for i in range(5):
        patient = await _seed_patient(
            db, clinic["branch_id"],
            name=f"FollowPatient {i}",
            phone=f"+9188888{str(i).zfill(5)}",
        )
        tok = await _seed_token(
            db, clinic["branch_id"], doctor, patient,
            on_date=date(2026, 9, 1 + i), token_number=i + 1,
        )
        token_ids.append(tok.id)

    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2026-09-01", "date_to": "2026-09-05"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    assert r.json()["followups_scheduled"] == 5

    # Verify FollowupTask rows — branch_id scoped (Rule 1)
    result = await db.execute(
        select(FollowupTask).where(
            FollowupTask.branch_id == uuid.UUID(clinic["branch_id"]),
            FollowupTask.doctor_id == doctor.id,
            FollowupTask.task_type == "cascade_rebook",
        )
    )
    tasks = result.scalars().all()
    assert len(tasks) == 5

    task_token_ids = {t.token_id for t in tasks}
    assert task_token_ids == set(token_ids)


@pytest.mark.asyncio
async def test_post_unavailability_enqueues_cal_delete_for_slot_doctor_tokens(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """Slot-doctor token WITH google_calendar_event_id → CalendarWriteTask(operation='delete') enqueued."""
    doctor = await _seed_doctor(
        db, clinic["branch_id"],
        booking_type="appointment",
        name="Dr Slot Cal",
    )
    patient = await _seed_patient(db, clinic["branch_id"], name="Cal Patient", phone="+919777700001")
    tok = await _seed_token(
        db, clinic["branch_id"], doctor, patient,
        on_date=date(2026, 10, 1),
        token_number=1,
        google_calendar_event_id="evt_slot_abc123",
    )
    tok_id = tok.id

    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2026-10-01", "date_to": "2026-10-01"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    assert r.json()["cancelled_tokens"] == 1

    # Verify CalendarWriteTask row exists with operation='delete'
    result = await db.execute(
        select(CalendarWriteTask).where(
            CalendarWriteTask.branch_id == uuid.UUID(clinic["branch_id"]),
            CalendarWriteTask.token_id == tok_id,
            CalendarWriteTask.operation == "delete",
        )
    )
    cal_tasks = result.scalars().all()
    assert len(cal_tasks) == 1
    assert cal_tasks[0].google_event_id == "evt_slot_abc123"
    assert cal_tasks[0].status == "pending"


@pytest.mark.asyncio
async def test_post_unavailability_no_cal_enqueue_for_token_doctor_tokens(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """Token-doctor token (no google_calendar_event_id) → no CalendarWriteTask 'delete' row."""
    doctor = await _seed_doctor(
        db, clinic["branch_id"],
        booking_type="token",
        name="Dr Token NoCal",
    )
    patient = await _seed_patient(db, clinic["branch_id"], name="NoCal Patient", phone="+919666600001")
    tok = await _seed_token(
        db, clinic["branch_id"], doctor, patient,
        on_date=date(2026, 11, 1),
        token_number=1,
        google_calendar_event_id=None,  # no cal event
    )
    tok_id = tok.id

    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2026-11-01", "date_to": "2026-11-01"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text

    # Verify NO CalendarWriteTask delete row exists
    result = await db.execute(
        select(CalendarWriteTask).where(
            CalendarWriteTask.token_id == tok_id,
            CalendarWriteTask.operation == "delete",
        )
    )
    cal_tasks = result.scalars().all()
    assert len(cal_tasks) == 0


@pytest.mark.asyncio
async def test_post_unavailability_idempotent_on_overlap(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """POST same date range twice → second call adds 0 new unavailability rows.

    Tokens already cancelled on first call should not be re-counted (their
    status is already 'cancelled_by_clinic', not 'confirmed').
    """
    doctor = await _seed_doctor(db, clinic["branch_id"], name="Dr Idempotent")
    patient = await _seed_patient(db, clinic["branch_id"], name="Idem Patient", phone="+919555500001")
    await _seed_token(
        db, clinic["branch_id"], doctor, patient,
        on_date=date(2026, 12, 1), token_number=1,
    )

    payload = {"date_from": "2026-12-01", "date_to": "2026-12-03"}

    # First POST — creates 3 unavailability rows + cancels 1 token
    r1 = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json=payload,
        headers=_auth(org_admin_jwt),
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["unavailable_dates"] == 3
    assert d1["cancelled_tokens"] == 1

    # Second POST — same range; ON CONFLICT DO NOTHING → 0 new dates
    # Token already cancelled → not 'confirmed' → 0 cancelled this time
    r2 = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json=payload,
        headers=_auth(org_admin_jwt),
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["unavailable_dates"] == 0
    assert d2["cancelled_tokens"] == 0

    # Total unavailability rows in DB is still 3 (not 6)
    result = await db.execute(
        select(DoctorUnavailability).where(
            DoctorUnavailability.branch_id == uuid.UUID(clinic["branch_id"]),
            DoctorUnavailability.doctor_id == doctor.id,
        )
    )
    assert len(result.scalars().all()) == 3


@pytest.mark.asyncio
async def test_get_affected_returns_token_count_without_cancelling(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """GET /affected must return the would-be-cancelled count without actually cancelling."""
    doctor = await _seed_doctor(db, clinic["branch_id"], name="Dr PreFlight")

    for i in range(3):
        patient = await _seed_patient(
            db, clinic["branch_id"],
            name=f"Pre Patient {i}",
            phone=f"+9144444{str(i).zfill(5)}",
        )
        await _seed_token(
            db, clinic["branch_id"], doctor, patient,
            on_date=date(2027, 1, 5 + i), token_number=i + 1,
        )

    r = await client.get(
        f"/availability/{clinic['branch_id']}/{doctor.id}/affected",
        params={"from": "2027-01-05", "to": "2027-01-07"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 3
    assert len(data["tokens"]) == 3

    # Tokens must NOT be cancelled — preflight is read-only
    result = await db.execute(
        select(Token).where(
            Token.branch_id == uuid.UUID(clinic["branch_id"]),
            Token.doctor_id == doctor.id,
            Token.status == "confirmed",
        )
    )
    still_confirmed = result.scalars().all()
    assert len(still_confirmed) == 3


@pytest.mark.asyncio
async def test_delete_single_date_removes_row(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """DELETE /availability/{branch}/{doctor}/{date} removes exactly that one row."""
    doctor = await _seed_doctor(db, clinic["branch_id"], name="Dr DelDate")

    # First mark unavailable for 2 days
    r = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2027-02-10", "date_to": "2027-02-11"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200
    assert r.json()["unavailable_dates"] == 2

    # Delete only 2027-02-10
    r_del = await client.delete(
        f"/availability/{clinic['branch_id']}/{doctor.id}/2027-02-10",
        headers=_auth(org_admin_jwt),
    )
    assert r_del.status_code == 204, r_del.text

    # Verify: 2027-02-10 is gone; 2027-02-11 remains
    result = await db.execute(
        select(DoctorUnavailability).where(
            DoctorUnavailability.branch_id == uuid.UUID(clinic["branch_id"]),
            DoctorUnavailability.doctor_id == doctor.id,
        )
    )
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].date == date(2027, 2, 11)


@pytest.mark.asyncio
async def test_receptionist_can_get_and_post(
    client, db: AsyncSession, clinic, receptionist_jwt, org_admin_jwt
):
    """Receptionist marks doctor leave from the front desk (POST) + reads.
    Contract changed 2026-06-11 — reception owns the desk. Doctors still 403."""
    doctor = await _seed_doctor(db, clinic["branch_id"], name="Dr RoleCheck")

    await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2027-03-01", "date_to": "2027-03-01"},
        headers=_auth(org_admin_jwt),
    )

    r_get = await client.get(
        f"/availability/{clinic['branch_id']}/{doctor.id}/affected",
        params={"from": "2027-03-01", "to": "2027-03-01"},
        headers=_auth(receptionist_jwt),
    )
    assert r_get.status_code == 200, r_get.text

    r_list = await client.get(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        params={"from": "2027-03-01", "to": "2027-03-01"},
        headers=_auth(receptionist_jwt),
    )
    assert r_list.status_code == 200, r_list.text

    # Receptionist POST — now allowed (200)
    r_post = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2027-03-02", "date_to": "2027-03-02"},
        headers=_auth(receptionist_jwt),
    )
    assert r_post.status_code == 200, r_post.text

    # A doctor (not front-desk) must still be rejected on write
    doctor_jwt = _make_jwt(
        user_id=str(uuid.uuid4()),
        email="doc@clinic.test",
        role="doctor",
        branch_ids=[clinic["branch_id"]],
    )
    r_doc = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2027-03-03", "date_to": "2027-03-03"},
        headers=_auth(doctor_jwt),
    )
    assert r_doc.status_code == 403, r_doc.text


@pytest.mark.asyncio
async def test_cross_branch_403(
    client, db: AsyncSession, clinic, clinic_b, org_admin_jwt
):
    """org_admin from org A trying POST on org B's doctor → 403."""
    # Doctor belongs to clinic_b's branch
    doctor_b = await _seed_doctor(db, clinic_b["branch_id"], name="Dr CrossBranch")

    # org_admin_jwt is scoped to clinic A (different org)
    r = await client.post(
        f"/availability/{clinic_b['branch_id']}/{doctor_b.id}",
        json={"date_from": "2027-04-01", "date_to": "2027-04-01"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_super_admin_blocked_403(
    client, db: AsyncSession, clinic, super_admin_jwt
):
    """super_admin must be blocked by assert_branch_access → 403 on all endpoints."""
    doctor = await _seed_doctor(db, clinic["branch_id"], name="Dr SuperBlock")

    # POST
    r_post = await client.post(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        json={"date_from": "2027-05-01", "date_to": "2027-05-01"},
        headers=_auth(super_admin_jwt),
    )
    assert r_post.status_code == 403, r_post.text

    # GET list
    r_get = await client.get(
        f"/availability/{clinic['branch_id']}/{doctor.id}",
        params={"from": "2027-05-01", "to": "2027-05-01"},
        headers=_auth(super_admin_jwt),
    )
    assert r_get.status_code == 403, r_get.text

    # GET affected
    r_affected = await client.get(
        f"/availability/{clinic['branch_id']}/{doctor.id}/affected",
        params={"from": "2027-05-01", "to": "2027-05-01"},
        headers=_auth(super_admin_jwt),
    )
    assert r_affected.status_code == 403, r_affected.text

    # DELETE
    r_del = await client.delete(
        f"/availability/{clinic['branch_id']}/{doctor.id}/2027-05-01",
        headers=_auth(super_admin_jwt),
    )
    assert r_del.status_code == 403, r_del.text
