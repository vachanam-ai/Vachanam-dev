"""A doctor removed from the clinic must leave the analytics board.

Real report 2026-08-03 (Vinay): "i removed karishma from clinic. it doesn't got
reflected." She was gone from the doctor roster and from the voice agent (the
delete soft-deletes to status='inactive' and invalidates the clinic cache), but
the dashboard's "Doctors · 30d" panel kept listing her — flagged "needs
attention", prompting the desk to chase a doctor who no longer works there.

Cause: the per-doctor analytics queries join Doctor without filtering status.

Clinic-wide totals deliberately still include her past bookings: those consultations
really happened. This board answers "who is on the desk", not "what did we bill".
"""
import httpx
import pytest
import pytest_asyncio

from tests.integration.test_clinic_overview_lists import (
    _auth, _booking, _clinic, _doctor, _owner,
)


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _overview(client, org, b):
    tok = _owner(str(org.id), str(b.id))
    r = await client.get(
        "/analytics/overview", params={"branch_id": str(b.id)}, headers=_auth(tok)
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_removed_doctor_leaves_the_per_doctor_board(client, db):
    from datetime import date

    org, b = await _clinic(db)
    staying = await _doctor(db, b, "Dr Staying")
    leaving = await _doctor(db, b, "Dr Karishma")
    await _booking(db, b, staying, date.today(), None, "PatA")
    await _booking(db, b, leaving, date.today(), None, "PatB")

    before = await _overview(client, org, b)
    names = [row["doctor_name"] for row in before["by_doctor"]]
    assert "Dr Karishma" in names, "precondition: she is on the board while active"

    leaving.status = "inactive"
    await db.commit()

    after = await _overview(client, org, b)
    names = [row["doctor_name"] for row in after["by_doctor"]]
    assert "Dr Karishma" not in names
    assert "Dr Staying" in names, "removing one doctor must not hide the others"


@pytest.mark.asyncio
async def test_upcoming_leave_for_a_removed_doctor_is_not_shown(client, db):
    from datetime import date, timedelta

    from backend.models.schema import DoctorUnavailability

    org, b = await _clinic(db)
    gone = await _doctor(db, b, "Dr Gone")
    db.add(DoctorUnavailability(
        branch_id=b.id, doctor_id=gone.id,
        date=date.today() + timedelta(days=3), reason="holiday",
    ))
    gone.status = "inactive"
    await db.commit()

    body = await _overview(client, org, b)
    assert "Dr Gone" not in str(body["on_leave"])
