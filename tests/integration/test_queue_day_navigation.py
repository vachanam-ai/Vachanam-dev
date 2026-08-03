"""The queue must be able to show a day other than today.

Real report 2026-08-03 (Vinay): "Dr Vishnu Vardhan Reddy's appointments are not
getting reflected in website." He is an appointment doctor with no fixed hours —
he publishes a whole WEEK of varying sessions in advance, so his patients book
days ahead. /queue/{branch}/today was the only view of bookings anywhere in the
product, so every one of those bookings was invisible until the morning it
happened, and an empty diary was indistinguishable from a broken one.
"""
import uuid
from datetime import date, time, timedelta

import httpx
import pytest
import pytest_asyncio

from tests.integration.test_clinic_overview_lists import (
    _auth, _booking, _clinic, _doctor, _owner,
)


# Each integration module defines its own `client`; importing the fixture
# instead shadows the test parameter and ruff rejects it (F811).
@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.mark.asyncio
async def test_future_booking_is_invisible_on_today_but_visible_on_its_own_date(
    client, db
):
    org, b = await _clinic(db)
    d = await _doctor(db, b, "Dr Vishnu")
    target = date.today() + timedelta(days=4)
    await _booking(db, b, d, target, time(11, 0), "FuturePat")

    tok = _owner(str(org.id), str(b.id))

    today = await client.get(f"/queue/{b.id}/today", headers=_auth(tok))
    assert today.status_code == 200, today.text
    assert today.json()["summary"]["total"] == 0

    ahead = await client.get(
        f"/queue/{b.id}/today",
        params={"date": target.isoformat()},
        headers=_auth(tok),
    )
    assert ahead.status_code == 200, ahead.text
    body = ahead.json()
    assert body["date"] == target.isoformat()
    names = [
        p["patient_name"]
        for doc in body["doctors"] for p in doc["patients"]
    ]
    assert "FuturePat" in names


@pytest.mark.asyncio
async def test_malformed_date_is_a_clean_400_not_a_500(client, db):
    org, b = await _clinic(db)
    tok = _owner(str(org.id), str(b.id))
    r = await client.get(
        f"/queue/{b.id}/today", params={"date": "next-tuesday"}, headers=_auth(tok)
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_another_clinic_cannot_read_a_dated_queue(client, db):
    """RULE 1: the date parameter must not become a way around branch scoping."""
    _, mine = await _clinic(db)
    other_org, other = await _clinic(db)
    d = await _doctor(db, mine, "Dr Mine")
    target = date.today() + timedelta(days=2)
    await _booking(db, mine, d, target, time(9, 30), "MyPatient")

    intruder = _owner(str(other_org.id), str(other.id))
    r = await client.get(
        f"/queue/{mine.id}/today",
        params={"date": target.isoformat()},
        headers=_auth(intruder),
    )
    assert r.status_code in (403, 404), r.text
    assert "MyPatient" not in r.text


@pytest.mark.asyncio
async def test_past_days_remain_readable(client, db):
    """Yesterday's board is how a clinic reconciles who actually turned up."""
    org, b = await _clinic(db)
    d = await _doctor(db, b, "Dr Past")
    yesterday = date.today() - timedelta(days=1)
    await _booking(db, b, d, yesterday, time(10, 0), "PastPat")

    tok = _owner(str(org.id), str(b.id))
    r = await client.get(
        f"/queue/{b.id}/today",
        params={"date": yesterday.isoformat()},
        headers=_auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["total"] == 1
    assert uuid.UUID(r.json()["branch_id"]) == b.id
