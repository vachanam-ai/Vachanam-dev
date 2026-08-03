"""WA MVP1 Task 3: WhatsApp conversation state (last 10 turns + draft),
branch-scoped, over the existing (previously dead-code) `whatsapp_sessions`
table.

RULE 1 — the same patient phone at two clinics must never share a thread.
RULE 4/8 — not exercised here (no external call); RULE 9 — the module only
ever logs turn counts + phone[-4:], asserted indirectly by there being no
`text=` kwarg anywhere in wa_session.py (see module for the log calls).

This ships in the SAME commit as the docs/legal/*.md rewrite that discloses
this storage — see docs/superpowers/plans/2026-08-02-whatsapp-mvp1-plan.md
Task 3.
"""
import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from backend.models.schema import Branch, Organization, Patient, WhatsAppSession


async def make_branch(db, *, whatsapp_number):
    org = Organization(
        name="WaSessOrg", owner_phone="+919000700088",
        owner_email=f"wasess-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="WaSessBranch", clinic_phone="+914012340001",
        whatsapp_number=whatsapp_number, status="active",
    )
    db.add(b)
    await db.commit()
    return b


@pytest.mark.asyncio
async def test_session_keeps_last_10_turns_only(db):
    from backend.services import wa_session

    branch = await make_branch(db, whatsapp_number="+9155000000001")
    for i in range(15):
        await wa_session.append(db, branch.id, "919000000001", "patient", f"m{i}")
    turns = (await wa_session.load(db, branch.id, "919000000001"))["turns"]
    assert len(turns) == 10
    assert turns[-1]["text"] == "m14" and turns[0]["text"] == "m5"


@pytest.mark.asyncio
async def test_sessions_are_branch_scoped(db):
    """RULE 1 — the same patient phone at two clinics must not share a thread."""
    from backend.services import wa_session

    branch_a = await make_branch(db, whatsapp_number="+9155000000002")
    branch_b = await make_branch(db, whatsapp_number="+9155000000003")
    await wa_session.append(db, branch_a.id, "919000000001", "patient", "at A")

    assert (await wa_session.load(db, branch_b.id, "919000000001"))["turns"] == []
    a_turns = (await wa_session.load(db, branch_a.id, "919000000001"))["turns"]
    assert a_turns[0]["text"] == "at A"


@pytest.mark.asyncio
async def test_load_with_no_session_returns_empty_shape(db):
    from backend.services import wa_session

    branch = await make_branch(db, whatsapp_number="+9155000000004")
    assert await wa_session.load(db, branch.id, "919000000009") == {
        "turns": [], "draft": {},
    }


@pytest.mark.asyncio
async def test_append_preserves_draft_across_turns(db):
    """A booking draft mid-flow must survive further turns being appended —
    append only touches `turns`, never clobbers `draft`."""
    from backend.services import wa_session

    branch = await make_branch(db, whatsapp_number="+9155000000005")
    row = WhatsAppSession(
        branch_id=branch.id, patient_phone="919000000001",
        session_data={"turns": [], "draft": {"doctor_id": "d1", "date": "2026-08-05"}},
    )
    db.add(row)
    await db.commit()

    await wa_session.append(db, branch.id, "919000000001", "patient", "10:30 works")
    state = await wa_session.load(db, branch.id, "919000000001")
    assert state["draft"] == {"doctor_id": "d1", "date": "2026-08-05"}
    assert state["turns"][-1]["text"] == "10:30 works"


@pytest.mark.asyncio
async def test_clear_deletes_the_row(db):
    from backend.services import wa_session

    branch = await make_branch(db, whatsapp_number="+9155000000006")
    await wa_session.append(db, branch.id, "919000000001", "patient", "hi")
    await wa_session.clear(db, branch.id, "919000000001")
    assert (await wa_session.load(db, branch.id, "919000000001"))["turns"] == []


@pytest.mark.asyncio
async def test_patient_erasure_deletes_the_conversation(db):
    """Uses the shared erasure path (backend/services/patient_erasure.py),
    which nulls patient.phone in place — the phone must be captured BEFORE
    calling erase_patient_pii, or the post-erasure lookup is trivially empty
    for the wrong reason (looking up phone=None)."""
    from backend.services import wa_session
    from backend.services.patient_erasure import erase_patient_pii

    branch = await make_branch(db, whatsapp_number="+9155000000007")
    patient = Patient(
        branch_id=branch.id, name="Ravi", phone="+919000007554", is_primary=True,
    )
    db.add(patient)
    await db.flush()
    phone = patient.phone  # capture before erasure nulls it in-place

    await wa_session.append(db, branch.id, phone, "patient", "my knee hurts")
    await erase_patient_pii(db, patient)
    await db.commit()

    assert (await wa_session.load(db, branch.id, phone))["turns"] == []


@pytest.mark.asyncio
async def test_retention_prunes_sessions_idle_30_days(db):
    from backend.jobs.data_retention import run_data_retention

    branch = await make_branch(db, whatsapp_number="+9155000000008")
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)
    fresh_row = WhatsAppSession(
        branch_id=branch.id, patient_phone="919000000002",
        session_data={"turns": [{"role": "patient", "text": "hi", "at": "x"}],
                      "draft": {}},
    )
    stale_row = WhatsAppSession(
        branch_id=branch.id, patient_phone="919000000001",
        session_data={"turns": [{"role": "patient", "text": "old", "at": "x"}],
                      "draft": {}},
        updated_at=old,
    )
    db.add_all([fresh_row, stale_row])
    await db.commit()

    await run_data_retention()

    remaining = (await db.execute(
        select(WhatsAppSession.patient_phone).where(WhatsAppSession.branch_id == branch.id)
    )).scalars().all()
    assert remaining == ["919000000002"]
