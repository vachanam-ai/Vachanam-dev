"""Multi-tenant data isolation tests — CLAUDE.md Rule 1.

Per tester.md rule 9: data isolation must be tested with 2 orgs minimum.
A single-org test that "looks isolated" proves nothing. We create Org A AND
Org B with separate branches and verify cross-access is impossible at:
  (a) the WHERE branch_id clause (DB-layer tripwire)
  (b) the branch_guard middleware (would block before query runs in API layer)

This file covers (a) — the data layer. API-layer branch_guard tests live in
tests/integration/ once the HTTP layer comes up in Phase 4 main.py.
"""
from datetime import date

from sqlalchemy import select

from backend.models.schema import Branch, Doctor, Organization, Patient, Token


async def _build_clinic(db, org_name, owner_phone, branch_wa, owner_email):
    """Helper: create one Organization + Branch + Doctor + Patient, return all four."""
    org = Organization(
        name=org_name,
        owner_phone=owner_phone,
        owner_email=owner_email,
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name=f"{org_name} Branch",
        whatsapp_number=branch_wa,
        status="active",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name=f"Dr. {org_name}",
        booking_type="token",
        is_default_doctor=True,
        daily_token_limit=10,
        status="active",
    )
    db.add(doctor)
    await db.flush()

    patient = Patient(
        branch_id=branch.id,
        name=f"Patient of {org_name}",
        phone=f"+91{owner_phone[-10:]}",
    )
    db.add(patient)
    await db.commit()

    return org, branch, doctor, patient


async def test_branch_a_query_never_returns_branch_b_tokens(db):
    """Branch A WHERE branch_id=A returns ONLY Branch A tokens.

    Setup: two separate orgs, two branches, two doctors, two patients, two tokens.
    The branch_id WHERE clause must be the ground truth — even if branch_guard
    middleware has a bug, this DB-level filter prevents cross-tenant data leak.
    """
    org_a, branch_a, doctor_a, patient_a = await _build_clinic(
        db, "ClinicA", "+919111111111", "+919000000001", "a@clinic.test"
    )
    org_b, branch_b, doctor_b, patient_b = await _build_clinic(
        db, "ClinicB", "+919222222222", "+919000000002", "b@clinic.test"
    )

    today = date.today()
    token_a = Token(
        branch_id=branch_a.id,
        doctor_id=doctor_a.id,
        patient_id=patient_a.id,
        date=today,
        token_number=1,
        source="voice",
        status="confirmed",
    )
    token_b = Token(
        branch_id=branch_b.id,
        doctor_id=doctor_b.id,
        patient_id=patient_b.id,
        date=today,
        token_number=1,
        source="voice",
        status="confirmed",
    )
    db.add_all([token_a, token_b])
    await db.commit()

    # Branch A query — must return EXACTLY one row, and it must be token_a
    result_a = await db.execute(
        select(Token).where(Token.branch_id == branch_a.id, Token.date == today)
    )
    tokens_for_a = result_a.scalars().all()
    assert len(tokens_for_a) == 1, f"Branch A should see 1 token, saw {len(tokens_for_a)}"
    assert tokens_for_a[0].id == token_a.id
    assert tokens_for_a[0].branch_id == branch_a.id

    # Branch B query — must return EXACTLY one row, and it must be token_b
    result_b = await db.execute(
        select(Token).where(Token.branch_id == branch_b.id, Token.date == today)
    )
    tokens_for_b = result_b.scalars().all()
    assert len(tokens_for_b) == 1, f"Branch B should see 1 token, saw {len(tokens_for_b)}"
    assert tokens_for_b[0].id == token_b.id
    assert tokens_for_b[0].branch_id == branch_b.id

    # CRITICAL: there is no token visible to both branches
    a_ids = {t.id for t in tokens_for_a}
    b_ids = {t.id for t in tokens_for_b}
    assert a_ids.isdisjoint(b_ids), "Cross-branch token leak detected!"


async def test_branch_a_query_never_returns_branch_b_patients(db):
    """Same isolation principle for the patient registry.

    A patient registered at Clinic A must be invisible to Clinic B — even though
    both clinics may serve the same person, they don't share patient records.
    """
    org_a, branch_a, _, patient_a = await _build_clinic(
        db, "PatTestA", "+919333333333", "+919000000003", "patA@clinic.test"
    )
    org_b, branch_b, _, patient_b = await _build_clinic(
        db, "PatTestB", "+919444444444", "+919000000004", "patB@clinic.test"
    )

    result_a = await db.execute(select(Patient).where(Patient.branch_id == branch_a.id))
    patients_a = result_a.scalars().all()
    assert len(patients_a) == 1
    assert patients_a[0].id == patient_a.id

    result_b = await db.execute(select(Patient).where(Patient.branch_id == branch_b.id))
    patients_b = result_b.scalars().all()
    assert len(patients_b) == 1
    assert patients_b[0].id == patient_b.id

    # Even if they had the same phone number, branch_id filter keeps them separate
    assert patients_a[0].id != patients_b[0].id


async def test_branch_a_doctor_invisible_to_branch_b(db):
    """A doctor registered to Branch A cannot be found by a Branch B query.

    Prevents: malicious clinic looking up a competitor's doctor list via URL
    tampering or a bug that drops the branch_id filter.
    """
    org_a, branch_a, doctor_a, _ = await _build_clinic(
        db, "DocTestA", "+919555555555", "+919000000005", "docA@clinic.test"
    )
    org_b, branch_b, doctor_b, _ = await _build_clinic(
        db, "DocTestB", "+919666666666", "+919000000006", "docB@clinic.test"
    )

    # Branch B query for ALL doctors must NOT include doctor_a
    result = await db.execute(select(Doctor).where(Doctor.branch_id == branch_b.id))
    doctors_visible_to_b = result.scalars().all()
    visible_ids = {d.id for d in doctors_visible_to_b}
    assert doctor_a.id not in visible_ids
    assert doctor_b.id in visible_ids
