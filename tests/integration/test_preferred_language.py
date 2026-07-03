"""Per-caller language mapping (Vinay 2026-07-03 case 2).

get_preferred_language: primary wins on a shared phone, branch-scoped (RULE 1).
set_preferred_language: updates every row on the phone in THIS branch only,
rejects unknown codes. Reuses the real NOT NULL Organization/Branch fields.
"""
import uuid

import pytest

from agent.tools.booking_tools import get_preferred_language, set_preferred_language
from backend.models.schema import Branch, Organization, Patient

pytestmark = pytest.mark.asyncio

PHONE = "+919000000441"


def _org() -> Organization:
    tag = uuid.uuid4().hex[:8]
    return Organization(
        id=uuid.uuid4(),
        name="Org",
        owner_phone="+919999000088",
        owner_email=f"preflang-{tag}@clinic.test",
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
        emergency_contact="+913333000088",
        status="active",
        timezone="Asia/Kolkata",
    )


async def _setup(db):
    org = _org()
    br = _branch(org)
    db.add_all([org, br])
    await db.flush()
    return br


async def test_get_prefers_primary_row(db):
    br = await _setup(db)
    db.add_all([
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone=PHONE,
                is_primary=True, preferred_language="en"),
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Sita", phone=PHONE,
                is_primary=False, preferred_language="hi"),
    ])
    await db.flush()
    assert await get_preferred_language(br.id, PHONE, db) == "en"


async def test_get_none_when_unmapped(db):
    br = await _setup(db)
    db.add(Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone=PHONE,
                   is_primary=True))
    await db.flush()
    assert await get_preferred_language(br.id, PHONE, db) is None
    # No record at all -> None too.
    assert await get_preferred_language(br.id, "+919000000442", db) is None


async def test_set_updates_all_rows_branch_scoped(db):
    br1 = await _setup(db)
    br2 = await _setup(db)
    p1 = Patient(id=uuid.uuid4(), branch_id=br1.id, name="Ravi", phone=PHONE, is_primary=True)
    p2 = Patient(id=uuid.uuid4(), branch_id=br1.id, name="Sita", phone=PHONE, is_primary=False)
    other = Patient(id=uuid.uuid4(), branch_id=br2.id, name="Ravi", phone=PHONE, is_primary=True)
    db.add_all([p1, p2, other])
    await db.flush()

    updated = await set_preferred_language(br1.id, PHONE, "en", db)
    assert updated == 2
    await db.refresh(p1)
    await db.refresh(p2)
    await db.refresh(other)
    assert p1.preferred_language == "en"
    assert p2.preferred_language == "en"
    # RULE 1: the other clinic's record with the same phone is untouched.
    assert other.preferred_language is None


async def test_set_rejects_unknown_code(db):
    br = await _setup(db)
    with pytest.raises(ValueError):
        await set_preferred_language(br.id, PHONE, "fr", db)


async def test_set_returns_zero_without_patient_row(db):
    br = await _setup(db)
    assert await set_preferred_language(br.id, "+919000000443", "en", db) == 0
