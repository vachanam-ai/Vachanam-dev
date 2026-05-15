import asyncio
import pytest
import pytest_asyncio
from datetime import date, timedelta
from uuid import uuid4

from backend.models.schema import Organization, Branch, Doctor
from agent.tools.booking_tools import assign_token


@pytest_asyncio.fixture
async def concurrent_clinic(db):
    org = Organization(
        name="Concurrent Test Clinic",
        owner_phone="+919988776655",
        owner_email="concurrent@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Concurrent Branch",
        whatsapp_number="+911234567890",
        status="active",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Concurrent",
        specialization="general_physician",
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=50,
        status="active",
    )
    db.add(doctor)
    await db.commit()
    return {"branch": branch, "doctor": doctor}


@pytest.mark.asyncio
async def test_five_concurrent_callers_get_unique_tokens(concurrent_clinic, db):
    """
    5 callers attempt to book simultaneously.
    CRITICAL: All successful bookings must have unique token numbers.
    No token number may appear twice.
    """
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=5)

    async def book_one_caller() -> dict:
        return await assign_token(doctor.id, branch.id, booking_date, db)

    results = await asyncio.gather(*[book_one_caller() for _ in range(5)])

    successful = [r for r in results if r["success"]]
    token_numbers = [r["token_number"] for r in successful]

    assert len(successful) == 5, f"Expected 5 successes, got {len(successful)}"
    assert len(set(token_numbers)) == 5, (
        f"Duplicate tokens found! Numbers: {sorted(token_numbers)}"
    )
    assert sorted(token_numbers) == list(range(1, 6)), (
        f"Expected sequential 1-5, got {sorted(token_numbers)}"
    )


@pytest.mark.asyncio
async def test_concurrent_callers_at_limit_boundary(concurrent_clinic, db):
    """
    49 tokens pre-booked. Then 3 callers arrive simultaneously.
    Exactly 1 should succeed (gets token 50). 2 should get 'full'.
    Counter after: must be exactly 50 (rollbacks applied for the 2 failures).
    """
    import redis.asyncio as aioredis
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=6)

    # Pre-fill 49 tokens
    for _ in range(49):
        result = await assign_token(doctor.id, branch.id, booking_date, db)
        assert result["success"] is True

    # 3 callers race for the last token
    results = await asyncio.gather(*[
        assign_token(doctor.id, branch.id, booking_date, db)
        for _ in range(3)
    ])

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, f"Expected 1 success at limit, got {len(successes)}"
    assert len(failures) == 2
    assert successes[0]["token_number"] == 50

    # Verify Redis counter is exactly 50 (not 51 or 52 — rollbacks worked)
    r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
    counter = int(await r.get(f"token:{doctor.id}:{branch.id}:{booking_date}") or 0)
    assert counter == 50, f"Expected Redis counter=50 after rollbacks, got {counter}"
    await r.aclose()
