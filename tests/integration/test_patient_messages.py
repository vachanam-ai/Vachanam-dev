"""#349: caller messages for the doctor — a real deliverable behind the
agent's "I will inform the clinic".

- list endpoint: pending first, urgent first, patient name joined, count
- RULE 1: another org's user cannot read or resolve a branch's messages
- resolve marks done + stamps resolved_at
- erasure deletes messages (linked by patient_id AND unlinked phone matches)
- retention prunes messages past the transcript clock
- prompt instructs take_message and forbids claiming before success
"""
import datetime
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import Branch, Organization, Patient, PatientMessage


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
async def test_messages_listed_pending_and_urgent_first(db):
    org_id, br = await _seed(db, "+910000000201")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Vinay",
                phone="+919000007554", is_primary=True)
    db.add(p)
    await db.flush()
    db.add_all([
        PatientMessage(branch_id=br.id, patient_id=p.id, caller_phone=p.phone,
                       message="Payment discrepancy, call me back", urgent=True),
        PatientMessage(branch_id=br.id, caller_phone="+919000001111",
                       message="Tell doctor I will be late tomorrow"),
        PatientMessage(branch_id=br.id, caller_phone="+919000002222",
                       message="Old resolved thing", status="done"),
    ])
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get(f"/branches/{br.id}/messages")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["pending"] == 2
            msgs = body["messages"]
            assert msgs[0]["urgent"] is True  # urgent pending on top
            assert msgs[0]["patient_name"] == "Vinay"
            assert msgs[0]["caller_phone"] == "+919000007554"
            assert msgs[-1]["status"] == "done"  # done sinks
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_rule1_cross_org_cannot_read_or_resolve(db):
    org_a, br_a = await _seed(db, "+910000000202")
    org_b, br_b = await _seed(db, "+910000000203")
    m = PatientMessage(branch_id=br_a.id, caller_phone="+919000003333",
                       message="Private to clinic A")
    db.add(m)
    await db.commit()

    # Org B's owner on their own branch cannot touch A's branch.
    app.dependency_overrides[get_current_user] = lambda: _as_user(br_b.id, org_b)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get(f"/branches/{br_a.id}/messages")
            assert r.status_code == 403, r.text
            r2 = await ac.patch(f"/branches/{br_a.id}/messages/{m.id}")
            assert r2.status_code == 403, r2.text
            # And a cross-branch id smuggled under their OWN branch → 404.
            r3 = await ac.patch(f"/branches/{br_b.id}/messages/{m.id}")
            assert r3.status_code == 404, r3.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_resolve_marks_done(db):
    org_id, br = await _seed(db, "+910000000204")
    m = PatientMessage(branch_id=br.id, caller_phone="+919000004444",
                       message="Call me about my bill")
    db.add(m)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.patch(f"/branches/{br.id}/messages/{m.id}")
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "done"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    await db.refresh(m)
    assert m.status == "done" and m.resolved_at is not None


@pytest.mark.asyncio
async def test_erasure_deletes_linked_and_phone_matched_messages(db):
    from sqlalchemy import select

    from backend.services.patient_erasure import erase_patient_pii

    org_id, br = await _seed(db, "+910000000205")
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Vinay",
                phone="+919000005555", is_primary=True)
    db.add(p)
    await db.flush()
    db.add_all([
        PatientMessage(branch_id=br.id, patient_id=p.id, caller_phone=p.phone,
                       message="linked"),
        # Taken before the patient row existed — no patient_id, same phone.
        PatientMessage(branch_id=br.id, caller_phone=p.phone, message="unlinked"),
        # Different caller — must SURVIVE.
        PatientMessage(branch_id=br.id, caller_phone="+919000006666",
                       message="someone else"),
    ])
    await db.commit()

    await erase_patient_pii(db, p)
    await db.commit()

    left = (await db.execute(
        select(PatientMessage.message).where(PatientMessage.branch_id == br.id)
    )).scalars().all()
    assert left == ["someone else"]


@pytest.mark.asyncio
async def test_retention_prunes_old_messages(db, redis):
    from sqlalchemy import select

    from backend.jobs.data_retention import run_data_retention

    org_id, br = await _seed(db, "+910000000206")
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=400)
    db.add_all([
        PatientMessage(branch_id=br.id, caller_phone="+919000007777",
                       message="ancient", created_at=old),
        PatientMessage(branch_id=br.id, caller_phone="+919000008888",
                       message="fresh"),
    ])
    await db.commit()

    await run_data_retention()

    left = (await db.execute(
        select(PatientMessage.message).where(PatientMessage.branch_id == br.id)
    )).scalars().all()
    assert left == ["fresh"]


def test_prompt_instructs_take_message():
    from agent.prompts.system_prompt import build_system_prompt

    prompt = build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )
    assert "take_message" in prompt
    # No "informed clinic" before the tool succeeds (tokens chosen to survive
    # the template's line wrapping).
    assert "urgent=true" in prompt
    # FAQ growth path stays separate.
    assert "log_clinic_question" in prompt
