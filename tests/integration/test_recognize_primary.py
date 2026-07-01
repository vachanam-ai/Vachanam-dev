"""Task 7: recognize_caller_name returns the PRIMARY patient's name.

On a shared family phone (several patients, one number), the agent should greet
the person who owns the number (Patient.is_primary=True) instead of asking
"who are you?". Still branch-scoped (RULE 1); None only when no patient / no
primary and not a single distinct name.

Uses the real Organization/Branch NOT NULL fields (owner_phone, owner_email,
plan/status; whatsapp_number/status) — the brief's fixtures were illustrative.
"""
import uuid

import pytest

from agent.tools.booking_tools import recognize_caller_name
from backend.models.schema import Branch, Organization, Patient

pytestmark = pytest.mark.asyncio


def _org() -> Organization:
    tag = uuid.uuid4().hex[:8]
    return Organization(
        id=uuid.uuid4(),
        name="Org",
        owner_phone="+919999000077",
        owner_email=f"primary-{tag}@clinic.test",
        plan="clinic",
        status="active",
    )


def _branch(org: Organization) -> Branch:
    tag = uuid.uuid4().hex[:8]
    return Branch(
        id=uuid.uuid4(),
        org_id=org.id,
        name="Br",
        whatsapp_number=f"+9111{tag}",
        did_number=f"+9122{tag}",
        emergency_contact="+913333000077",
        status="active",
        timezone="Asia/Kolkata",
    )


async def test_returns_primary_when_multiple_names(db):
    org = _org()
    br = _branch(org)
    db.add_all([org, br])
    await db.flush()
    db.add_all([
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone="+919000000030", is_primary=True),
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Sita", phone="+919000000030", is_primary=False),
    ])
    await db.flush()
    name = await recognize_caller_name(br.id, "+919000000030", db)
    assert name == "Ravi"


async def test_single_name_no_primary_flag_still_returned(db):
    """Legacy row: no primary flagged but exactly one distinct name -> greet."""
    org = _org()
    br = _branch(org)
    db.add_all([org, br])
    await db.flush()
    db.add(
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Lakshmi", phone="+919000000032", is_primary=False)
    )
    await db.flush()
    name = await recognize_caller_name(br.id, "+919000000032", db)
    assert name == "Lakshmi"


async def test_none_when_no_patient(db):
    org = _org()
    br = _branch(org)
    db.add_all([org, br])
    await db.flush()
    assert await recognize_caller_name(br.id, "+919000000031", db) is None
