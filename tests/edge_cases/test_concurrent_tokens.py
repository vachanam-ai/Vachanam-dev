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


async def test_concurrent_assigns_at_boundary_get_unique_numbers(db, redis):
    """
    99 seats CONFIRMED (limit=100). 10 callers race to assign.

    RULE 2 core (no two patients ever get the SAME number) must hold: every
    successful assign gets a UNIQUE token number via the atomic Redis INCR.
    Capacity itself is enforced on the CONFIRMED-seat count at confirm_booking
    (a cancelled token frees its seat); assign-time holds are advisory, so all
    10 may receive a (unique) number here — none may collide.
    """
    from backend.models.schema import Patient, Token

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

    # Pre-fill 99 CONFIRMED seats (the real capacity measure).
    async with AsyncSessionLocal() as session:
        patient = Patient(
            branch_id=branch.id, name="Filler", phone="+919666000099", age=30
        )
        session.add(patient)
        await session.flush()
        for n in range(1, 100):
            session.add(Token(
                branch_id=branch.id, doctor_id=doctor.id, patient_id=patient.id,
                date=booking_date, token_number=n, status="confirmed", source="voice",
            ))
        await session.commit()

    # 10 callers race to assign. db_confirmed=99 < 100, so all hold a number.
    async def try_book() -> dict:
        async with AsyncSessionLocal() as session:
            return await assign_token(doctor.id, branch.id, booking_date, session)

    results = await asyncio.gather(*[try_book() for _ in range(10)])

    successes = [r for r in results if r["success"]]
    numbers = [r["token_number"] for r in successes]

    # The ONLY hard guarantee under concurrency: no two callers share a number.
    assert len(numbers) == len(set(numbers)), (
        f"Duplicate token numbers issued under concurrency: {sorted(numbers)}"
    )
    # And every issued number is past the 99 already-confirmed seats.
    assert all(n > 99 for n in numbers), f"Number reused a confirmed seat: {numbers}"
