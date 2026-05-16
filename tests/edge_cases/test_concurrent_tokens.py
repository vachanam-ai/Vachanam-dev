import asyncio
import pytest_asyncio
from datetime import date, timedelta

from backend.database import AsyncSessionLocal
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
        did_number="+911234567891",
        emergency_contact="+911234567892",
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


async def test_five_concurrent_callers_get_unique_tokens(concurrent_clinic, redis):
    """
    5 callers attempt to book simultaneously.
    CRITICAL: All successful bookings must have unique token numbers.
    """
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=5)

    async def book_one_caller() -> dict:
        async with AsyncSessionLocal() as session:
            return await assign_token(doctor.id, branch.id, booking_date, session)

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


async def test_concurrent_callers_at_limit_boundary(concurrent_clinic, redis):
    """
    49 tokens pre-booked. Then 3 callers arrive simultaneously.
    Exactly 1 should succeed (gets token 50). 2 should get 'full'.
    Counter after: must be exactly 50 (rollbacks applied for the 2 failures).
    """
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=6)

    # Pre-fill 49 tokens using independent sessions
    async with AsyncSessionLocal() as session:
        for _ in range(49):
            result = await assign_token(doctor.id, branch.id, booking_date, session)
            assert result["success"] is True

    # 3 callers race for the last token, each with their own session
    async def try_book() -> dict:
        async with AsyncSessionLocal() as session:
            return await assign_token(doctor.id, branch.id, booking_date, session)

    results = await asyncio.gather(*[try_book() for _ in range(3)])

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, f"Expected 1 success at limit, got {len(successes)}"
    assert len(failures) == 2
    assert successes[0]["token_number"] == 50

    counter = int(await redis.get(f"token:{doctor.id}:{branch.id}:{booking_date}") or 0)
    assert counter == 50, f"Expected Redis counter=50 after rollbacks, got {counter}"
