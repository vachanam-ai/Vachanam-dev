"""Task 8 review: DB-backed run-loop tests for next_visit_followup_caller.

These exercise run_next_visit_followups end-to-end (the unit suite only covers
the pure _is_due helper). `_dispatch` is monkeypatched so NO network/LiveKit is
touched. `now` is pinned inside calling hours (09:00-20:00 IST) so the test is
hour-stable on any clock.

Seed notes (create_all enforces FKs/NOT NULL — same as Tasks 3/5/6/7):
  - Organization first (Branch.org_id RESTRICT FK)
  - Branch.whatsapp_number NOT NULL + unique
  - Doctor.booking_type NOT NULL ('appointment' for this feature)
"""
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import backend.jobs.next_visit_followup_caller as job
from backend.models.schema import (
    Branch, Doctor, Patient, Organization, TreatmentNote, FollowupTask,
)

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 6, 22)
NOW_IN_HOURS = datetime(2026, 6, 22, 10, 0, tzinfo=IST)   # 10:00 IST → inside [9,20)


async def _seed(db, *, is_final=False, next_reporting=date(2026, 6, 25), phone="+919000000040", consent=True, plan="clinic"):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099040",
                        owner_email=f"owner-{org_id}@c.com", plan=plan))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C",
                whatsapp_number=f"+9100{uuid.uuid4().hex[:9]}", timezone="Asia/Kolkata")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="appointment")
    # followup_consent=True: these tests exercise the DISPATCH paths; the
    # consent gate (#303) has its own dedicated test below.
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone=phone,
                  followup_consent=consent)
    db.add_all([doc, pat]); await db.flush()
    note = TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                         visit_date=date(2026, 6, 21), next_reporting_date=next_reporting,
                         is_final=is_final)
    db.add(note); await db.flush()
    task = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                        task_type="next_visit_book", channel="voice", status="pending",
                        scheduled_date=TODAY, treatment_note_id=note.id,
                        what_to_ask="how is the pain?")
    db.add(task); await db.commit()
    return br, doc, pat, note, task


@pytest.mark.asyncio
async def test_run_dispatch_success_marks_completed(db, monkeypatch, redis):
    br, doc, pat, note, task = await _seed(db)
    seen = {}

    async def fake_dispatch(t, branch, doctor, patient, target_date):
        seen["target_date"] = target_date
        # capture the metadata _dispatch WOULD build (mirror production keys)
        meta = {"call_type": t.task_type, "message": t.what_to_ask or ""}
        if target_date and t.task_type == "next_visit_book":
            meta["target_date"] = target_date
        seen["meta"] = meta
        return True

    monkeypatch.setattr(job, "_dispatch", fake_dispatch)
    n = await job.run_next_visit_followups(now=NOW_IN_HOURS)
    assert n == 1
    await db.refresh(task)
    assert task.status == "completed"
    # target_date is the note's next_reporting_date, and RULE 9 is respected:
    assert seen["meta"]["target_date"] == date(2026, 6, 25).isoformat()
    assert "steps_performed" not in seen["meta"]
    assert "next_steps" not in seen["meta"]


@pytest.mark.asyncio
async def test_run_dispatch_failure_stays_pending_for_retry(db, monkeypatch, redis):
    br, doc, pat, note, task = await _seed(db)

    async def fake_dispatch(*a, **k):
        return False

    monkeypatch.setattr(job, "_dispatch", fake_dispatch)
    n = await job.run_next_visit_followups(now=NOW_IN_HOURS)
    assert n == 0
    await db.refresh(task)
    # NOT in_progress, NOT completed — re-dialable next tick (self-healing)
    assert task.status == "pending"
    assert task.attempt_count == 1


@pytest.mark.asyncio
async def test_run_final_note_completes_without_dialing(db, monkeypatch, redis):
    br, doc, pat, note, task = await _seed(db, is_final=True)
    called = {"n": 0}

    async def fake_dispatch(*a, **k):
        called["n"] += 1
        return True

    monkeypatch.setattr(job, "_dispatch", fake_dispatch)
    n = await job.run_next_visit_followups(now=NOW_IN_HOURS)
    assert n == 0
    await db.refresh(task)
    assert task.status == "completed"
    assert called["n"] == 0   # treatment closed → never dialed


@pytest.mark.asyncio
async def test_no_consent_skips_call_and_completes_task(db, monkeypatch, redis):
    """#303 (DPDP): followup_consent=False must actually stop the phone from
    ringing — policy §9 promises withdrawal works. Task closes, zero dispatch."""
    br, doc, pat, note, task = await _seed(db, consent=False)
    called = {"n": 0}

    async def fake_dispatch(*a, **k):
        called["n"] += 1
        return True

    monkeypatch.setattr(job, "_dispatch", fake_dispatch)
    n = await job.run_next_visit_followups(now=NOW_IN_HOURS)
    assert n == 0
    assert called["n"] == 0
    await db.refresh(task)
    assert task.status == "completed"


@pytest.mark.asyncio
async def test_starter_plan_skips_followup_loop(db, monkeypatch, redis):
    """Repricing 2026-07-11: the treatment follow-up voice loop is a
    Clinic/Multi feature. A solo/Starter org's task closes silently — zero
    dispatch, no crash, no retry loop."""
    br, doc, pat, note, task = await _seed(db, plan="solo")
    called = {"n": 0}

    async def fake_dispatch(*a, **k):
        called["n"] += 1
        return True

    monkeypatch.setattr(job, "_dispatch", fake_dispatch)
    n = await job.run_next_visit_followups(now=NOW_IN_HOURS)
    assert n == 0
    assert called["n"] == 0
    await db.refresh(task)
    assert task.status == "completed"
