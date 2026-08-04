"""2026-07-03 evening fixes.

T1: treatment-patients returns ONE ROW PER (patient, doctor) — a patient in
    two concurrent treatments (dental + skin) shows twice, and the notes list
    filters by doctor thread.
T2: follow-up prompts no longer push a booking on a problem report (prompt
    text assertions) and doctor_advice only books when doctor/patient initiate.
T3: log_clinic_question writes a branch-scoped row; GET /faq returns it in
    `asked`.
"""
import uuid
import datetime

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.middleware.auth_middleware import get_current_user, CurrentUser
from backend.models.schema import (
    Branch, ClinicQuestion, Doctor, Organization, Patient, TreatmentNote,
)
from agent.livekit_minimal.agent import (
    DOCTOR_ADVICE_PROMPT_EXTRA, NEXT_VISIT_PROMPT_EXTRA,
)


def _as_user(branch_id, org_id, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@c.com", role=role,
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


async def _seed(db, wa):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099099",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number=wa)
    db.add(br)
    await db.flush()
    return org_id, br


@pytest.mark.asyncio
async def test_t1_one_row_per_patient_doctor_pair(db):
    org_id, br = await _seed(db, "+910000000095")
    d1 = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr. Srinivas", booking_type="appointment")
    d2 = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr. Lakshmi", booking_type="appointment")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Vinay", phone="+919000007554", is_primary=True)
    db.add_all([d1, d2, p])
    await db.flush()
    today = datetime.date.today()
    db.add_all([
        TreatmentNote(id=uuid.uuid4(), branch_id=br.id, doctor_id=d1.id, patient_id=p.id,
                      visit_date=today, steps_performed="dental work"),
        TreatmentNote(id=uuid.uuid4(), branch_id=br.id, doctor_id=d2.id, patient_id=p.id,
                      visit_date=today, steps_performed="skin work"),
    ])
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get(f"/treatment/branches/{br.id}/treatment-patients")
            assert r.status_code == 200, r.text
            rows = [x for x in r.json()["patients"] if x["patient_id"] == str(p.id)]
            assert len(rows) == 2, f"expected one row per doctor thread, got {rows}"
            assert {x["doctor_name"] for x in rows} == {"Dr. Srinivas", "Dr. Lakshmi"}

            # notes list scoped to one thread
            n1 = await ac.get(f"/treatment/patients/{p.id}/treatment-notes",
                              params={"branch_id": str(br.id), "doctor_id": str(d1.id)})
            notes = n1.json()["notes"]
            assert len(notes) == 1 and notes[0]["steps_performed"] == "dental work"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_t2_followup_prompts_dont_push_booking_on_problem():
    """SUPERSEDED IN PART, 2026-08-04 (Vinay), and deliberately kept rather
    than deleted so the reversal is visible.

    The 07-03 rule was "a problem report ends with inform-doctor, not a sales
    pitch" — no booking offered to a patient in pain. Vinay reversed it for the
    FIRST follow-up call: the doctor reads that report afterwards and may want
    them in sooner, and if no booking exists there is nothing to move. So the
    next_visit call now offers however they answer.

    What did NOT change, and is what this test now guards: the problem still
    reaches the doctor, the offer is never dressed up as treatment (RULE 7),
    and a doctor_advice relay still does not offer a visit off a NEW problem —
    there the doctor has already spoken, so a fresh complaint goes back to them.
    """
    nv = NEXT_VISIT_PROMPT_EXTRA
    assert "STILL offer the visit" in nv          # the reversal
    assert "I will inform the doctor" in nv       # unchanged: it reaches them
    # RULE 7 — offering a slot is not medical advice; claiming it helps would be
    assert "Never say the appointment will fix anything" in nv
    assert "never say it can wait" in nv
    assert "If they say no, accept it" in nv      # never argued into it
    da = DOCTOR_ADVICE_PROMPT_EXTRA
    assert "never push one otherwise" in da
    assert "do NOT offer a visit" in da


@pytest.mark.asyncio
async def test_t3_clinic_question_logged_and_listed(db):
    org_id, br = await _seed(db, "+910000000096")
    await db.commit()
    db.add(ClinicQuestion(branch_id=br.id, question="Do you have X-ray facility?",
                          caller_last4="7554"))
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            g = await ac.get(f"/branches/{br.id}/faq")
            assert g.status_code == 200, g.text
            asked = g.json()["asked"]
            assert any(a["question"] == "Do you have X-ray facility?" for a in asked)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_t3_prompt_has_faq_gap_fallback():
    from agent.prompts.system_prompt import build_system_prompt

    prompt = build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )
    assert "log_clinic_question" in prompt
    # #418 rewording: the agent itself checks with the doctor and the clinic
    # calls back — never "confirm at the clinic".
    assert "డాక్టర్ గారిని అడిగి చెప్పిస్తాను" in prompt
