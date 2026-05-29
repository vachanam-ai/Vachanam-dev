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

    # daily_token_limit=200 so the 100-caller race test can succeed for all callers
    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Concurrent",
        specialization="general_physician",
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=200,
        status="active",
    )
    db.add(doctor)
    await db.commit()
    return {"branch": branch, "doctor": doctor}


async def test_100_concurrent_callers_get_unique_sequential_tokens(concurrent_clinic, redis):
    """
    100 callers attempt to book simultaneously.
    CRITICAL: All successful bookings must have unique, sequential token numbers (1..100).
    N=100 satisfies tester.md rule 5 (concurrency tests run N≥100).
    """
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=5)

    async def book_one_caller() -> dict:
        # Each coroutine MUST open its own AsyncSession — sharing is not concurrent-safe
        async with AsyncSessionLocal() as session:
            return await assign_token(doctor.id, branch.id, booking_date, session)

    results = await asyncio.gather(*[book_one_caller() for _ in range(100)])

    successful = [r for r in results if r["success"]]
    token_numbers = [r["token_number"] for r in successful]

    assert len(successful) == 100, f"Expected 100 successes, got {len(successful)}"
    assert len(set(token_numbers)) == 100, (
        f"Duplicate tokens found! Got {len(set(token_numbers))} unique out of 100"
    )
    assert sorted(token_numbers) == list(range(1, 101)), (
        f"Expected sequential 1..100, got min={min(token_numbers)} max={max(token_numbers)}"
    )

    counter = int(await redis.get(f"token:{doctor.id}:{branch.id}:{booking_date}") or 0)
    assert counter == 100, f"Expected Redis counter=100, got {counter}"


async def test_10_concurrent_callers_at_limit_boundary(db, redis):
    """
    99 tokens pre-booked (limit=100). 10 callers race for token 100.
    Exactly 1 must succeed. 9 must get 'full'. Redis counter must end at exactly 100
    (the 9 rejected callers must have rolled back via DECR).
    """
    org = Organization(
        name="Boundary Test Clinic",
        owner_phone="+919876543210",
        owner_email="boundary@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Boundary Branch",
        whatsapp_number="+919876543211",
        did_number="+919876543212",
        emergency_contact="+919876543213",
        status="active",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Boundary",
        specialization="general_physician",
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=100,
        status="active",
    )
    db.add(doctor)
    await db.commit()

    booking_date = date.today() + timedelta(days=7)

    # Pre-fill 99 tokens
    async with AsyncSessionLocal() as session:
        for _ in range(99):
            result = await assign_token(doctor.id, branch.id, booking_date, session)
            assert result["success"] is True

    counter_before = int(await redis.get(f"token:{doctor.id}:{branch.id}:{booking_date}") or 0)
    assert counter_before == 99

    # 10 callers race for token 100
    async def try_book() -> dict:
        async with AsyncSessionLocal() as session:
            return await assign_token(doctor.id, branch.id, booking_date, session)

    results = await asyncio.gather(*[try_book() for _ in range(10)])

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, (
        f"Expected exactly 1 success at limit boundary, got {len(successes)}: {results}"
    )
    assert len(failures) == 9, f"Expected 9 failures, got {len(failures)}"
    assert successes[0]["token_number"] == 100, (
        f"Expected token 100, got {successes[0]['token_number']}"
    )
    assert all(f["reason"] == "full" for f in failures), (
        f"All failures must have reason='full', got: {[f.get('reason') for f in failures]}"
    )

    # Redis counter must be EXACTLY 100 (the 9 over-limit DECRs rolled back)
    counter_after = int(await redis.get(f"token:{doctor.id}:{branch.id}:{booking_date}") or 0)
    assert counter_after == 100, (
        f"Expected Redis counter=100 after rollbacks (9 over-limit DECRed), got {counter_after}"
    )
