import pytest_asyncio
from datetime import date, timedelta

from backend.models.schema import Organization, Branch, Doctor
from agent.tools.booking_tools import check_availability, assign_token


@pytest_asyncio.fixture
async def seeded_clinic(db):
    """Create a minimal clinic: org → branch → doctor (token type, limit 20)."""
    org = Organization(
        name="Test Clinic",
        owner_phone="+919999999999",
        owner_email="test@testclinic.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Test Clinic Branch",
        whatsapp_number="+911111111111",
        did_number="+912222222222",
        emergency_contact="+913333333333",
        status="active",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Test",
        specialization="general_physician",
        routing_keywords=["fever", "cold", "headache"],
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=20,
        status="active",
    )
    db.add(doctor)
    await db.commit()
    return {"org": org, "branch": branch, "doctor": doctor}


async def test_check_availability_returns_speech_string(seeded_clinic, db, redis):
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today()

    result = await check_availability(doctor.id, branch.id, today, db)

    assert "token" in result.lower() or "available" in result.lower()
    assert str(today.day) in result or "0" in result


async def test_assign_token_returns_sequential_numbers(seeded_clinic, db, redis):
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today() + timedelta(days=1)

    result1 = await assign_token(doctor.id, branch.id, today, db)
    result2 = await assign_token(doctor.id, branch.id, today, db)

    assert result1["success"] is True
    assert result2["success"] is True
    assert result2["token_number"] == result1["token_number"] + 1


async def test_assign_token_respects_daily_limit(seeded_clinic, db, redis):
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today() + timedelta(days=2)

    for _ in range(20):
        await assign_token(doctor.id, branch.id, today, db)

    result = await assign_token(doctor.id, branch.id, today, db)
    assert result["success"] is False
    assert result["reason"] == "full"


async def test_token_rollback_on_full(seeded_clinic, db, redis):
    """After a 'full' rejection, the Redis counter must not have incremented."""
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today() + timedelta(days=3)

    for _ in range(20):
        await assign_token(doctor.id, branch.id, today, db)

    counter_before = int(await redis.get(f"token:{doctor.id}:{branch.id}:{today}") or 0)

    await assign_token(doctor.id, branch.id, today, db)  # 21st — should fail + DECR

    counter_after = int(await redis.get(f"token:{doctor.id}:{branch.id}:{today}") or 0)
    assert counter_after == counter_before  # DECR rolled it back
