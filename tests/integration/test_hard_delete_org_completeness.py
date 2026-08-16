"""A clinic erasure must remove restricted rows, logins, and patient data."""
from __future__ import annotations

import uuid
from datetime import date, time, timedelta

import pytest
from sqlalchemy import func, select
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
    WhatsAppDelivery,
)
from backend.routers.admin import _hard_delete_org

pytestmark = pytest.mark.asyncio


async def _clinic(db: AsyncSession, name: str = "Doomed"):
    suffix = uuid.uuid4().hex[:10]
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        plan="solo",
        status="cancelled",
        owner_phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        owner_email=f"{suffix}@example.com",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        id=uuid.uuid4(),
        org_id=org.id,
        name="Main",
        timezone="Asia/Kolkata",
        whatsapp_number=f"+9188{uuid.uuid4().int % 100000000:08d}",
        status="active",
    )
    db.add(branch)
    await db.flush()
    doctor = Doctor(
        id=uuid.uuid4(),
        branch_id=branch.id,
        name="Dr Test",
        specialization="General",
        status="active",
        booking_type="appointment",
        working_hours_start=time(9),
        working_hours_end=time(17),
        available_weekdays=[0, 1, 2, 3, 4, 5, 6],
    )
    db.add(doctor)
    await db.flush()
    return org, branch, doctor


async def test_restricted_schedule_and_whatsapp_rows_do_not_block_erasure(db: AsyncSession):
    org, branch, doctor = await _clinic(db)
    tomorrow = date.today() + timedelta(days=1)
    db.add(
        DoctorDateSchedule(
            id=uuid.uuid4(),
            branch_id=branch.id,
            doctor_id=doctor.id,
            date=tomorrow,
            sessions=[{"start": "09:00", "end": "12:00"}],
        )
    )
    db.add(
        WhatsAppDelivery(
            id=uuid.uuid4(),
            branch_id=branch.id,
            event_key=f"test:{uuid.uuid4()}",
            purpose="booking_confirm",
            recipient_phone="+919900000001",
            values_json=["Patient"],
            buttons_json=[],
        )
    )
    db.add(
        AddonPurchase(
            id=uuid.uuid4(),
            org_id=org.id,
            branch_id=branch.id,
            kind="whatsapp_addon",
            amount=1499,
            gst=0,
            razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    assert await db.get(Organization, org.id) is None
    assert await db.get(Branch, branch.id) is None
    for model in (DoctorDateSchedule, WhatsAppDelivery, AddonPurchase):
        count = (
            await db.execute(
                select(func.count()).select_from(model).where(model.branch_id == branch.id)
            )
        ).scalar_one()
        assert count == 0


async def test_erasure_removes_patient_records_and_all_tenant_logins(db: AsyncSession):
    org, branch, doctor = await _clinic(db)
    patient = Patient(
        id=uuid.uuid4(),
        branch_id=branch.id,
        name="Patient",
        phone="+919900000002",
    )
    db.add(patient)
    await db.flush()
    token_id = uuid.uuid4()
    db.add(
        Token(
            id=token_id,
            branch_id=branch.id,
            doctor_id=doctor.id,
            patient_id=patient.id,
            date=date.today(),
            token_number=1,
            appointment_time=time(10),
            status="confirmed",
            source="voice",
        )
    )
    db.add(
        ClinicQuestion(
            id=uuid.uuid4(),
            branch_id=branch.id,
            question="What are the timings?",
            caller_phone=patient.phone,
            caller_last4="0002",
        )
    )
    emails = []
    for role in ("org_admin", "receptionist", "doctor"):
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        emails.append(email)
        db.add(
            User(
                id=uuid.uuid4(),
                org_id=org.id,
                email=email,
                name=role,
                role=role,
                branch_ids=[str(branch.id)],
            )
        )
    orphan_email = f"orphan-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        User(
            id=uuid.uuid4(),
            org_id=None,
            email=orphan_email,
            name="Orphan",
            role="receptionist",
            branch_ids=[str(branch.id)],
        )
    )
    await db.commit()

    await _hard_delete_org(db, org)
    await db.commit()

    assert (await db.execute(select(User).where(User.email.in_([*emails, orphan_email])))).scalars().all() == []
    assert await db.get(Patient, patient.id) is None
    assert await db.get(Token, token_id) is None


async def test_erasure_never_touches_another_clinic_or_platform_login(db: AsyncSession):
    doomed, doomed_branch, _ = await _clinic(db, "Doomed")
    keeper, keeper_branch, keeper_doctor = await _clinic(db, "Keeper")
    platform = User(
        id=uuid.uuid4(),
        org_id=None,
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        role="super_admin",
        branch_ids=[str(doomed_branch.id)],
    )
    db.add(platform)
    await db.commit()

    await _hard_delete_org(db, doomed)
    await db.commit()

    assert await db.get(Organization, keeper.id) is not None
    assert await db.get(Branch, keeper_branch.id) is not None
    assert await db.get(Doctor, keeper_doctor.id) is not None
    assert await db.get(User, platform.id) is not None
