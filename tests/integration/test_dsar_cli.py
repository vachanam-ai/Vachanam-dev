"""TD-028: scripts/dsar.py — the DSAR handler behind the privacy policy's
7-day SLA. export / correct / delete / withdraw, always branch-scoped (RULE 1),
delete rides the SAME shared erasure path as the retention job.
"""
import uuid
from datetime import date

import pytest

from backend.models.schema import Branch, Doctor, FollowupTask, Organization, Patient, Token
from backend.services.patient_erasure import ERASED_NAME
from scripts.dsar import run as dsar_run

pytestmark = pytest.mark.asyncio


async def _seed(db):
    org = Organization(name="DSAR Clinic", owner_phone="+919000000080",
                       owner_email=f"d-{uuid.uuid4().hex[:8]}@t.in",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    branch = Branch(org_id=org.id, name="Main", whatsapp_number=f"+91986{uuid.uuid4().hex[:7]}")
    other = Branch(org_id=org.id, name="Other", whatsapp_number=f"+91987{uuid.uuid4().hex[:7]}")
    db.add_all([branch, other])
    await db.flush()
    doc = Doctor(branch_id=branch.id, name="Dr A", specialization="dental",
                 booking_type="token")
    db.add(doc)
    await db.flush()
    pat = Patient(branch_id=branch.id, name="Ravi Kumar", phone="+919866011111")
    db.add(pat)
    await db.flush()
    db.add(Token(branch_id=branch.id, doctor_id=doc.id, patient_id=pat.id,
                 token_number=7, date=date.today(), status="confirmed", source="voice"))
    db.add(FollowupTask(branch_id=branch.id, doctor_id=doc.id, patient_id=pat.id,
                        task_type="doctor_advice", channel="voice", status="pending",
                        what_to_ask="pain level?"))
    await db.commit()
    return branch, other, pat


async def test_export_dumps_patient_data(db, capsys):
    branch, _, _ = await _seed(db)
    rc = await dsar_run("+919866011111", str(branch.id), "export")
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ravi Kumar" in out
    assert '"token_number": 7' in out
    assert "pain level?" in out


async def test_rule1_wrong_branch_finds_nothing(db):
    _, other, _ = await _seed(db)
    rc = await dsar_run("+919866011111", str(other.id), "export")
    assert rc == 1  # branch-scoped: same phone, wrong branch → not found


async def test_withdraw_stops_pending_followups_keeps_identity(db):
    from sqlalchemy import select

    branch, _, pat = await _seed(db)
    pat_id = pat.id
    rc = await dsar_run("+919866011111", str(branch.id), "withdraw")
    assert rc == 0
    db.expire_all()
    task = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat_id))).scalar_one()
    fresh = (await db.execute(select(Patient).where(Patient.id == pat_id))).scalar_one()
    assert task.status == "completed"
    assert fresh.name == "Ravi Kumar"  # withdraw ≠ erase


async def test_delete_erases_via_shared_path(db):
    from sqlalchemy import select

    branch, _, pat = await _seed(db)
    pat_id = pat.id
    rc = await dsar_run("+919866011111", str(branch.id), "delete")
    assert rc == 0
    db.expire_all()
    fresh = (await db.execute(select(Patient).where(Patient.id == pat_id))).scalar_one()
    assert fresh.name == ERASED_NAME
    assert fresh.phone in (None, "")
    assert fresh.anonymized_at is not None


async def test_correct_updates_name(db):
    from sqlalchemy import select

    branch, _, pat = await _seed(db)
    pat_id = pat.id
    rc = await dsar_run("+919866011111", str(branch.id), "correct", name="Ravi K")
    assert rc == 0
    db.expire_all()
    fresh = (await db.execute(select(Patient).where(Patient.id == pat_id))).scalar_one()
    assert fresh.name == "Ravi K"
