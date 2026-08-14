"""Deleting a clinic must erase it — every table, or the delete fails loudly.

Vinay 2026-08-14: "EVEN AFTER DELETING CLINIC. EVERYTHING STILL PRESENT.
deleting means earising account as such entirely. when i try to login in
again. it should trat as a new clinic. not just manipulating. actually delete."

`_hard_delete_org` listed 18 tables and the schema had 25 with a tenant FK.
Two of the seven it missed — doctor_date_schedules and whatsapp_deliveries —
are ondelete=RESTRICT, so a clinic that had ever published a doctor's dates or
queued a WhatsApp message could not be deleted at all: Postgres refused, the
request 500'd, and the UI showed nothing. The other five were CASCADE and
would have been swept silently, which is worse in its own way — an erasure
promise resting on an FK default nobody checked.

The first test is the one that matters: it reads the LIVE foreign-key graph
rather than a hand-written list, so a table added next year is caught the day
it appears.
"""
from __future__ import annotations

import uuid
from datetime import date, time, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import (
    AddonPurchase,
    Branch,
    ClinicQuestion,
    Doctor,
    DoctorDateSchedule,
    Organization,
    Patient,
    Token,
    User,
)
from backend.routers.admin import _hard_delete_org

pytestmark = pytest.mark.asyncio

# Tables that legitimately outlive a deleted clinic.
#   audit_log     — the erasure itself must remain auditable (no tenant FK)
#   support_tickets — org FK is SET NULL by design; rows are deleted separately
_ALLOWED_SURVIVORS = {"audit_log", "support_tickets"}


async def test_every_tenant_table_is_covered(db: AsyncSession):
    """Read the real FK graph and assert the delete function names each table.

    A hand-maintained list rots. This does not.
    """
    rows = (
        await db.execute(
            text(
                """
                select distinct tc.table_name
                from information_schema.table_constraints tc
                join information_schema.constraint_column_usage ccu
                  on ccu.constraint_name = tc.constraint_name
                where tc.constraint_type = 'FOREIGN KEY'
                  and ccu.table_name in ('organizations', 'branches')
                """
            )
        )
    ).scalars().all()

    from pathlib import Path

    source = Path("backend/routers/admin.py").read_text(encoding="utf-8")
    body = source.split("async def _hard_delete_org", 1)[1].split("\n@router", 1)[0]

    # Map table -> model class name, then require the model to appear.
    import backend.models.schema as schema

    by_table = {
        obj.__tablename__: name
        for name, obj in vars(schema).items()
        if hasattr(obj, "__tablename__")
    }

    missing = []
    for table in sorted(rows):
        if table in _ALLOWED_SURVIVORS or table in ("branches", "organizations"):
            continue
        model = by_table.get(table)
        if model and model not in body:
            missing.append(f"{table} (model {model})")

    assert not missing, (
        "_hard_delete_org does not touch these tenant tables, so a clinic's "
        "data survives deletion (CASCADE) or the delete fails (RESTRICT):\n  "
        + "\n  ".join(missing)
    )


async def _clinic(db: AsyncSession):
    org = Organization(
        id=uuid.uuid4(), name="Doomed", plan="solo", status="cancelled",
        owner_phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        owner_email=f"{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        id=uuid.uuid4(), org_id=org.id, name="Main", timezone="Asia/Kolkata",
        whatsapp_number=f"+9188{uuid.uuid4().int % 100000000:08d}", status="active",
    )
    db.add(branch)
    await db.flush()
    doctor = Doctor(
        id=uuid.uuid4(), branch_id=branch.id, name="Doc", specialization="Dental",
        status="active", booking_type="appointment",
        working_hours_start=time(9, 0), working_hours_end=time(17, 0),
        available_weekdays=[0, 1, 2, 3, 4],
    )
    db.add(doctor)
    await db.flush()
    return org, branch, doctor


async def test_a_clinic_with_published_dates_can_still_be_deleted(db: AsyncSession):
    """doctor_date_schedules is RESTRICT — this is the row that blocked it.

    Any clinic using a date-specific doctor (Vishnu at Sri Venkateshwara) hit
    this, and the failure surfaced as "delete did nothing".
    """
    org, branch, doctor = await _clinic(db)
    db.add(
        DoctorDateSchedule(
            id=uuid.uuid4(), branch_id=branch.id, doctor_id=doctor.id,
            date=date.today() + timedelta(days=1),
            sessions=[{"start": "10:00", "end": "12:00"}],
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    remaining = (
        await db.execute(
            select(func.count()).select_from(DoctorDateSchedule)
            .where(DoctorDateSchedule.branch_id == branch.id)
        )
    ).scalar_one()
    assert remaining == 0
    assert await db.get(Organization, org.id) is None


async def test_a_paid_addon_does_not_survive_the_clinic(db: AsyncSession):
    """A billing artefact outliving the clinic is both a leak and a blocker."""
    org, branch, _ = await _clinic(db)
    db.add(
        AddonPurchase(
            id=uuid.uuid4(), org_id=org.id, branch_id=branch.id,
            kind="whatsapp_addon", amount=1499, gst=0,
            razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    left = (
        await db.execute(
            select(func.count()).select_from(AddonPurchase)
            .where(AddonPurchase.org_id == org.id)
        )
    ).scalar_one()
    assert left == 0


async def test_the_logins_go_too_so_signing_in_again_is_a_new_clinic(db: AsyncSession):
    """The requirement in Vinay's own words: not a deactivation, an erasure.

    With no user row, the next Google sign-in has nothing to attach to and the
    signup flow treats it as a brand new clinic.
    """
    org, branch, _ = await _clinic(db)
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    db.add(
        User(
            id=uuid.uuid4(), org_id=org.id, email=email, name="Owner",
            role="org_admin", branch_ids=[str(branch.id)],
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    survivor = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    assert survivor is None, "the login survived — signing in would resume the old clinic"


async def test_patient_data_is_actually_gone(db: AsyncSession):
    """DPDP erasure: the patient records are the point."""
    org, branch, doctor = await _clinic(db)
    patient = Patient(
        id=uuid.uuid4(), branch_id=branch.id, name="Someone",
        phone=f"+9199{uuid.uuid4().int % 100000000:08d}",
    )
    db.add(patient)
    await db.flush()
    db.add(
        Token(
            id=uuid.uuid4(), branch_id=branch.id, doctor_id=doctor.id,
            patient_id=patient.id, date=date.today(), token_number=1,
            appointment_time=time(10, 0), status="confirmed", source="voice",
        )
    )
    db.add(
        ClinicQuestion(
            id=uuid.uuid4(), branch_id=branch.id, question="what are timings?",
            caller_phone="+919900000000", caller_last4="0000",
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    for model in (Patient, Token, ClinicQuestion):
        left = (
            await db.execute(
                select(func.count()).select_from(model)
                .where(model.branch_id == branch.id)
            )
        ).scalar_one()
        assert left == 0, f"{model.__tablename__} survived the erasure"

    assert await db.get(Branch, branch.id) is None
    assert await db.get(Organization, org.id) is None


async def test_another_clinic_is_untouched(db: AsyncSession):
    """RULE 1: erasing one tenant must not reach into another."""
    doomed_org, _, _ = await _clinic(db)
    keeper_org, keeper_branch, keeper_doc = await _clinic(db)
    keeper_patient = Patient(
        id=uuid.uuid4(), branch_id=keeper_branch.id, name="Keeper",
        phone=f"+9197{uuid.uuid4().int % 100000000:08d}",
    )
    db.add(keeper_patient)
    await db.commit()

    await _hard_delete_org(db, doomed_org)
    await db.commit()

    assert await db.get(Organization, keeper_org.id) is not None
    assert await db.get(Branch, keeper_branch.id) is not None
    assert await db.get(Doctor, keeper_doc.id) is not None
    assert await db.get(Patient, keeper_patient.id) is not None


async def test_every_staff_login_dies_with_the_clinic(db: AsyncSession):
    """Vinay 2026-08-14: "all linked doctors, receptionists accounts should
    also be deleted."

    Not just the owner. A doctor or receptionist login surviving means someone
    can still authenticate against a clinic that no longer exists.
    """
    org, branch, _ = await _clinic(db)
    emails = {}
    for role in ("org_admin", "receptionist", "doctor"):
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        emails[role] = email
        db.add(
            User(
                id=uuid.uuid4(), org_id=org.id, email=email, name=role,
                role=role, branch_ids=[str(branch.id)],
            )
        )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    for role, email in emails.items():
        left = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        assert left is None, f"{role} login survived the clinic deletion"


async def test_an_orphaned_login_scoped_to_the_branch_also_goes(db: AsyncSession):
    """User.org_id is NULLABLE.

    A login whose org_id was never set but whose branch_ids still point at this
    clinic would survive the org_id sweep, keep working, and carry a dead
    tenant scope. Second sweep catches it.
    """
    org, branch, _ = await _clinic(db)
    email = f"orphan-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        User(
            id=uuid.uuid4(), org_id=None, email=email, name="Orphan",
            role="receptionist", branch_ids=[str(branch.id)],
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    left = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    assert left is None, "an orphaned branch-scoped login survived"


async def test_platform_accounts_are_never_touched(db: AsyncSession):
    """super_admin and support have no org_id BY DESIGN.

    The orphan sweep must not mistake them for clinic staff — deleting a
    clinic must never remove Vachanam's own logins.
    """
    org, branch, _ = await _clinic(db)
    platform = {}
    for role in ("super_admin", "support"):
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        platform[role] = email
        db.add(
            User(
                id=uuid.uuid4(), org_id=None, email=email, name=role,
                role=role, branch_ids=[str(branch.id)],  # worst case: scoped in
            )
        )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    for role, email in platform.items():
        survivor = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        assert survivor is not None, f"clinic deletion removed the {role} account"


async def test_another_clinics_staff_are_untouched(db: AsyncSession):
    """RULE 1 for logins specifically."""
    doomed, _, _ = await _clinic(db)
    keeper, keeper_branch, _ = await _clinic(db)
    email = f"keeper-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        User(
            id=uuid.uuid4(), org_id=keeper.id, email=email, name="Keeper",
            role="receptionist", branch_ids=[str(keeper_branch.id)],
        )
    )
    await db.commit()

    await _hard_delete_org(db, doomed)
    await db.commit()

    survivor = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    assert survivor is not None, "erasing one clinic deleted another clinic's staff"

