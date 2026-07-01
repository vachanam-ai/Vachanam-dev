import datetime
import uuid

import pytest
from sqlalchemy import select, text

from backend.models.schema import Branch, Doctor, Organization, Patient, Token
from backend.services.patient_dedup import BACKFILL_PRIMARY_SQL, MERGE_SQL


async def _branch(db):
    """Seed a minimal org/branch/doctor. Field names + NOT NULL columns match
    the real schema (Organization.owner_phone/owner_email, Branch.whatsapp_number
    are required and unique) — the brief's fixture was illustrative only."""
    uniq = uuid.uuid4().hex[:8]
    org = Organization(
        id=uuid.uuid4(),
        name="Org",
        owner_phone="+919900000000",
        owner_email=f"owner-{uniq}@example.com",
        plan="clinic",
    )
    br = Branch(
        id=uuid.uuid4(),
        org_id=org.id,
        name="Br",
        whatsapp_number=f"+9199{uniq}",
        timezone="Asia/Kolkata",
    )
    doc = Doctor(
        id=uuid.uuid4(),
        branch_id=br.id,
        name="Dr",
        specialization="dental",
        booking_type="token",
        status="active",
    )
    db.add_all([org, br, doc])
    await db.flush()
    return br, doc


@pytest.mark.asyncio
async def test_merge_repoints_and_dedups(db):
    br, doc = await _branch(db)
    # create_all builds Task 1's live unique index; it would block seeding the
    # dups on flush. Drop it BEFORE seeding — the migration (Task 3) instead
    # creates it AFTER the merge, so a dropped index here mirrors that order.
    await db.execute(text("DROP INDEX IF EXISTS uq_patient_branch_phone_name"))
    # Two rows, same phone, same name different case -> duplicates.
    canonical = Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone="+919000000001")
    dup = Patient(id=uuid.uuid4(), branch_id=br.id, name="ravi", phone="+919000000001")
    db.add_all([canonical, dup])
    await db.flush()
    # created_at ordering: canonical first. Force it deterministically.
    await db.execute(
        text("UPDATE patients SET created_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": str(canonical.id)},
    )
    tok = Token(
        id=uuid.uuid4(),
        branch_id=br.id,
        doctor_id=doc.id,
        patient_id=dup.id,
        date=datetime.date.today(),
        token_number=1,
        status="confirmed",
        source="voice",
    )
    db.add(tok)
    await db.flush()

    for stmt in MERGE_SQL:
        await db.execute(text(stmt))
    await db.flush()

    # Raw SQL bypassed the ORM identity map; populate_existing forces the
    # re-query to overwrite the cached instances with fresh DB values.
    remaining = (
        await db.execute(
            select(Patient)
            .where(Patient.branch_id == br.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].id == canonical.id
    moved = (
        await db.execute(
            select(Token)
            .where(Token.id == tok.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert moved.patient_id == canonical.id


@pytest.mark.asyncio
async def test_backfill_sets_one_primary_per_phone(db):
    br, doc = await _branch(db)
    a = Patient(id=uuid.uuid4(), branch_id=br.id, name="Amma", phone="+919000000002")
    b = Patient(id=uuid.uuid4(), branch_id=br.id, name="Nanna", phone="+919000000002")
    c = Patient(id=uuid.uuid4(), branch_id=br.id, name="Walkin", phone=None)
    db.add_all([a, b, c])
    await db.flush()
    await db.execute(
        text("UPDATE patients SET created_at = now() - interval '1 hour' WHERE id = :i"),
        {"i": str(a.id)},
    )
    for stmt in BACKFILL_PRIMARY_SQL:
        await db.execute(text(stmt))
    await db.flush()
    # Raw SQL bypassed the ORM identity map; populate_existing forces the
    # re-query to overwrite the cached instances with fresh DB values.
    rows = {
        p.id: p
        for p in (
            await db.execute(
                select(Patient)
                .where(Patient.branch_id == br.id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    }
    assert rows[a.id].is_primary is True  # earliest on the shared phone
    assert rows[b.id].is_primary is False
    assert rows[c.id].is_primary is True  # NULL-phone -> own primary
