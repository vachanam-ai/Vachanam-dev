"""Integration tests for /doctors CRUD router (Task 8).

Covers:
  - test_list_doctors_branch_isolation
  - test_create_appointment_doctor_auto_defaults_reminders_on
  - test_create_token_doctor_auto_defaults_reminders_off
  - test_receptionist_cannot_create_doctor (403)
  - test_org_admin_can_create_doctor (201)
  - test_patch_doctor_working_hours_triggers_recurring_cal_upsert (mock GoogleCalendarService)
  - test_soft_delete_sets_status_inactive
  - test_stop_walkins_today_sets_date_to_today (receptionist can call)
  - test_super_admin_blocked_on_all_endpoints (403)

All JWT tokens are hand-crafted from settings.jwt_secret so no real auth flow
is required. Uses httpx.AsyncClient + ASGITransport (same event loop as pytest-asyncio)
so the conftest `db` fixture's patched AsyncSessionLocal is picked up by the router's
Depends(get_db).  The `redis` fixture pre-flushes and satisfies the rate-limiter.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.schema import Branch, Doctor, Organization

# ---------------------------------------------------------------------------
# JWT factory
# ---------------------------------------------------------------------------

_ALGO = "HS256"


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
# HTTP client fixture — async, same event loop as pytest-asyncio
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(redis):
    """Async httpx client wired to the app via ASGITransport.

    The `redis` fixture ensures the rate-limiter Redis pool is initialised.
    Because this client runs in the same asyncio event loop as the `db`
    fixture, the conftest-patched AsyncSessionLocal is visible to the router's
    Depends(get_db) — no event-loop mismatch.
    """
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# DB fixtures — create org / branch / user / doctor per test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def clinic(db: AsyncSession):
    """Minimal org + branch A for tests that need an isolated branch."""
    org = Organization(
        name="Test Clinic A",
        owner_phone="+919000000001",
        owner_email=f"owner-a-{uuid.uuid4()}@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Branch A",
        whatsapp_number=f"+91800{str(uuid.uuid4().int)[:7]}",
        status="active",
    )
    db.add(branch)
    await db.commit()

    # Capture immutable values now — avoids DetachedInstanceError later
    return {
        "org_id": str(org.id),
        "branch_id": str(branch.id),
    }


@pytest_asyncio.fixture
async def clinic_b(db: AsyncSession):
    """Second org + branch for isolation tests."""
    org = Organization(
        name="Test Clinic B",
        owner_phone="+919000000002",
        owner_email=f"owner-b-{uuid.uuid4()}@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Branch B",
        whatsapp_number=f"+91700{str(uuid.uuid4().int)[:7]}",
        status="active",
    )
    db.add(branch)
    await db.commit()

    return {
        "org_id": str(org.id),
        "branch_id": str(branch.id),
    }


@pytest_asyncio.fixture
async def org_admin_jwt(clinic):
    """JWT for org_admin on clinic A's org."""
    return _make_jwt(
        user_id=str(uuid.uuid4()),
        email="admin-a@test.com",
        role="org_admin",
        org_id=clinic["org_id"],
        branch_ids=[clinic["branch_id"]],
    )


@pytest_asyncio.fixture
async def receptionist_jwt(clinic):
    """JWT for receptionist on branch A."""
    return _make_jwt(
        user_id=str(uuid.uuid4()),
        email="recep-a@test.com",
        role="receptionist",
        org_id=clinic["org_id"],
        branch_ids=[clinic["branch_id"]],
    )


@pytest_asyncio.fixture
async def super_admin_jwt():
    """JWT for super_admin (Vinay)."""
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
    name: str = "Dr Seed",
    status: str = "active",
) -> str:
    """Seed one doctor row, return doctor_id as str."""
    doc = Doctor(
        branch_id=uuid.UUID(branch_id),
        name=name,
        booking_type=booking_type,
        available_weekdays=[0, 1, 2, 3, 4],
        pre_appointment_reminder=(booking_type == "appointment"),
        post_treatment_followup=(booking_type == "appointment"),
        status=status,
    )
    db.add(doc)
    await db.commit()
    return str(doc.id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_doctors_branch_isolation(
    client,
    db: AsyncSession,
    clinic,
    clinic_b,
    org_admin_jwt,
):
    """org_admin on branch_a must only see branch_a doctors, never branch_b."""
    await _seed_doctor(db, clinic["branch_id"], name="Dr A Only")
    await _seed_doctor(db, clinic_b["branch_id"], name="Dr B Only")

    r = await client.get(
        f"/doctors/{clinic['branch_id']}",
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text
    names = [d["name"] for d in r.json()]
    assert "Dr A Only" in names
    assert "Dr B Only" not in names


@pytest.mark.asyncio
async def test_create_appointment_doctor_auto_defaults_reminders_on(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """POST with booking_type='appointment' must auto-set both reminders to True."""
    r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={
            "name": "Dr Reddy",
            "booking_type": "appointment",
            "working_hours_start": "09:00",
            "working_hours_end": "17:00",
        },
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["pre_appointment_reminder"] is True
    assert d["post_treatment_followup"] is True


@pytest.mark.asyncio
async def test_create_token_doctor_auto_defaults_reminders_off(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """POST with booking_type='token' must auto-set both reminders to False."""
    r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={
            "name": "Dr Sharma",
            "booking_type": "token",
            "daily_token_limit": 10,
            "working_hours_start": "09:00",
            "working_hours_end": "13:00",
        },
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["pre_appointment_reminder"] is False
    assert d["post_treatment_followup"] is False


@pytest.mark.asyncio
async def test_reminder_explicit_override_respected(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """Caller can override auto-defaults; explicit False wins over auto True."""
    r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={
            "name": "Dr Override",
            "booking_type": "appointment",
            "pre_appointment_reminder": False,
            "post_treatment_followup": False,
        },
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["pre_appointment_reminder"] is False
    assert d["post_treatment_followup"] is False


@pytest.mark.asyncio
async def test_receptionist_cannot_create_doctor(
    client,
    db: AsyncSession,
    clinic,
    receptionist_jwt,
):
    """Receptionist role must get 403 on POST /doctors/{branch_id}."""
    r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={"name": "X", "booking_type": "token"},
        headers=_auth(receptionist_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_org_admin_can_create_doctor(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """org_admin must get 201 on POST /doctors/{branch_id}."""
    r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={"name": "Dr New", "booking_type": "token"},
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Dr New"


@pytest.mark.asyncio
async def test_patch_doctor_working_hours_triggers_recurring_cal_upsert(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """PATCH working_hours on a token-doctor with a calendar_id should call
    GoogleCalendarService.upsert_doctor_hours_event exactly once.

    The mock patches the class inside the doctors router module so the
    router's instantiation picks up the mock instance.
    """
    # Create a token doctor with a calendar_id set
    create_r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={
            "name": "Dr Cal Token",
            "booking_type": "token",
            "google_calendar_id": "some-cal@group.calendar.google.com",
            "working_hours_start": "09:00",
            "working_hours_end": "13:00",
            "available_weekdays": [0, 1, 2, 3, 4],
        },
        headers=_auth(org_admin_jwt),
    )
    assert create_r.status_code == 201, create_r.text
    doctor_id = create_r.json()["id"]

    # PATCH working_hours — should trigger upsert
    with patch("backend.routers.doctors.GoogleCalendarService") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.upsert_doctor_hours_event = AsyncMock(
            return_value="evt_recurring_999"
        )

        patch_r = await client.patch(
            f"/doctors/{clinic['branch_id']}/{doctor_id}",
            json={
                "name": "Dr Cal Token",
                "booking_type": "token",
                "working_hours_start": "10:00",
                "working_hours_end": "14:00",
            },
            headers=_auth(org_admin_jwt),
        )

    assert patch_r.status_code == 200, patch_r.text
    mock_instance.upsert_doctor_hours_event.assert_called_once()


async def test_patch_doctor_calendar_change_moves_recurring_event(
    client, db: AsyncSession, clinic, org_admin_jwt
):
    """TD-023: changing a doctor's calendar_id deletes the stale hours event
    from the OLD calendar and creates a fresh one on the NEW (no PATCH-404)."""
    create_r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={
            "name": "Dr Move", "booking_type": "token",
            "google_calendar_id": "old-cal@group.calendar.google.com",
            "working_hours_start": "09:00", "working_hours_end": "13:00",
            "available_weekdays": [0, 1, 2, 3, 4],
        },
        headers=_auth(org_admin_jwt),
    )
    assert create_r.status_code == 201, create_r.text
    doctor_id = create_r.json()["id"]

    # Pretend the recurring event was created on the OLD calendar.
    doc = (
        await db.execute(select(Doctor).where(Doctor.id == uuid.UUID(doctor_id)))
    ).scalar_one()
    doc.calendar_event_id_recurring = "evt_old_cal"
    await db.commit()

    with patch("backend.routers.doctors.GoogleCalendarService") as mock_cls:
        inst = mock_cls.return_value
        inst.delete_event = AsyncMock(return_value=None)
        inst.upsert_doctor_hours_event = AsyncMock(return_value="evt_new_cal")

        patch_r = await client.patch(
            f"/doctors/{clinic['branch_id']}/{doctor_id}",
            json={
                "name": "Dr Move", "booking_type": "token",
                "google_calendar_id": "new-cal@group.calendar.google.com",
            },
            headers=_auth(org_admin_jwt),
        )
    assert patch_r.status_code == 200, patch_r.text
    # Old event deleted from the OLD calendar...
    inst.delete_event.assert_awaited_once_with(
        "old-cal@group.calendar.google.com", "evt_old_cal"
    )
    # ...and the upsert created fresh (existing_event_id=None, not the stale id).
    _, kwargs = inst.upsert_doctor_hours_event.call_args
    assert kwargs["existing_event_id"] is None


@pytest.mark.asyncio
async def test_patch_appointment_doctor_does_not_trigger_recurring_event(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """PATCH on an appointment-type doctor must NOT call upsert_doctor_hours_event."""
    create_r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={
            "name": "Dr Slot",
            "booking_type": "appointment",
            "working_hours_start": "09:00",
            "working_hours_end": "17:00",
        },
        headers=_auth(org_admin_jwt),
    )
    assert create_r.status_code == 201, create_r.text
    doctor_id = create_r.json()["id"]

    with patch("backend.routers.doctors.GoogleCalendarService") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.upsert_doctor_hours_event = AsyncMock(
            return_value="evt_should_not_be_called"
        )

        patch_r = await client.patch(
            f"/doctors/{clinic['branch_id']}/{doctor_id}",
            json={
                "name": "Dr Slot",
                "booking_type": "appointment",
                "working_hours_start": "08:00",
                "working_hours_end": "16:00",
            },
            headers=_auth(org_admin_jwt),
        )

    assert patch_r.status_code == 200, patch_r.text
    mock_instance.upsert_doctor_hours_event.assert_not_called()


@pytest.mark.asyncio
async def test_soft_delete_sets_status_inactive(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """DELETE /doctors/{branch}/{doctor} must set status='inactive', not remove the row."""
    doctor_id = await _seed_doctor(db, clinic["branch_id"], name="Dr ToDelete")

    r = await client.delete(
        f"/doctors/{clinic['branch_id']}/{doctor_id}",
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 204, r.text

    # Confirm the doctor is gone from list (status=inactive excluded)
    list_r = await client.get(
        f"/doctors/{clinic['branch_id']}",
        headers=_auth(org_admin_jwt),
    )
    assert list_r.status_code == 200
    names = [d["name"] for d in list_r.json()]
    assert "Dr ToDelete" not in names

    # Confirm row still exists in DB with status=inactive
    result = await db.execute(
        select(Doctor).where(Doctor.id == uuid.UUID(doctor_id))
    )
    remaining = result.scalar_one_or_none()
    assert remaining is not None
    assert remaining.status == "inactive"


@pytest.mark.asyncio
async def test_receptionist_cannot_delete_doctor(
    client,
    db: AsyncSession,
    clinic,
    receptionist_jwt,
):
    """Receptionist role must get 403 on DELETE."""
    doctor_id = await _seed_doctor(db, clinic["branch_id"])

    r = await client.delete(
        f"/doctors/{clinic['branch_id']}/{doctor_id}",
        headers=_auth(receptionist_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_stop_walkins_today_sets_date_to_today(
    client,
    db: AsyncSession,
    clinic,
    receptionist_jwt,
):
    """PATCH .../stop-walkins-today must set walkins_closed_today_date to today.
    Receptionist role is allowed (spec §5.2 constraint 2).
    """
    doctor_id = await _seed_doctor(db, clinic["branch_id"], name="Dr Busy")

    r = await client.patch(
        f"/doctors/{clinic['branch_id']}/{doctor_id}/stop-walkins-today",
        headers=_auth(receptionist_jwt),
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["walkins_closed_today_date"] == date.today().isoformat()


@pytest.mark.asyncio
async def test_org_admin_can_stop_walkins_today(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """org_admin must also be able to call stop-walkins-today."""
    doctor_id = await _seed_doctor(db, clinic["branch_id"], name="Dr Busy2")

    r = await client.patch(
        f"/doctors/{clinic['branch_id']}/{doctor_id}/stop-walkins-today",
        headers=_auth(org_admin_jwt),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_super_admin_blocked_on_list(
    client,
    db: AsyncSession,
    clinic,
    super_admin_jwt,
):
    """super_admin must get 403 on GET /doctors/{branch_id}."""
    r = await client.get(
        f"/doctors/{clinic['branch_id']}",
        headers=_auth(super_admin_jwt),
    )
    assert r.status_code == 403, r.text
    assert "admin" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_super_admin_blocked_on_create(
    client,
    db: AsyncSession,
    clinic,
    super_admin_jwt,
):
    """super_admin must get 403 on POST /doctors/{branch_id}."""
    r = await client.post(
        f"/doctors/{clinic['branch_id']}",
        json={"name": "X", "booking_type": "token"},
        headers=_auth(super_admin_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_super_admin_blocked_on_patch(
    client,
    db: AsyncSession,
    clinic,
    super_admin_jwt,
):
    """super_admin must get 403 on PATCH /doctors/{branch_id}/{doctor_id}."""
    doctor_id = await _seed_doctor(db, clinic["branch_id"])

    r = await client.patch(
        f"/doctors/{clinic['branch_id']}/{doctor_id}",
        json={"name": "Y", "booking_type": "token"},
        headers=_auth(super_admin_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_super_admin_blocked_on_delete(
    client,
    db: AsyncSession,
    clinic,
    super_admin_jwt,
):
    """super_admin must get 403 on DELETE /doctors/{branch_id}/{doctor_id}."""
    doctor_id = await _seed_doctor(db, clinic["branch_id"])

    r = await client.delete(
        f"/doctors/{clinic['branch_id']}/{doctor_id}",
        headers=_auth(super_admin_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_super_admin_blocked_on_stop_walkins(
    client,
    db: AsyncSession,
    clinic,
    super_admin_jwt,
):
    """super_admin must get 403 on PATCH .../stop-walkins-today."""
    doctor_id = await _seed_doctor(db, clinic["branch_id"])

    r = await client.patch(
        f"/doctors/{clinic['branch_id']}/{doctor_id}/stop-walkins-today",
        headers=_auth(super_admin_jwt),
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_create_doctor_with_cal_upsert_failure_still_returns_201(
    client,
    db: AsyncSession,
    clinic,
    org_admin_jwt,
):
    """If upsert_doctor_hours_event raises, POST still returns 201 (best-effort)."""
    with patch("backend.routers.doctors.GoogleCalendarService") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.upsert_doctor_hours_event = AsyncMock(
            side_effect=Exception("Google API down")
        )

        r = await client.post(
            f"/doctors/{clinic['branch_id']}",
            json={
                "name": "Dr Resilient",
                "booking_type": "token",
                "google_calendar_id": "cal-id@group.calendar.google.com",
                "working_hours_start": "09:00",
                "working_hours_end": "13:00",
            },
            headers=_auth(org_admin_jwt),
        )

    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Dr Resilient"
