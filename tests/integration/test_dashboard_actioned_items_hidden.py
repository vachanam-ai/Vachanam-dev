"""Dashboard shows only what still needs action (Vinay 2026-08-03).

"messages and questions once answered should be deleted from this page. if
question converted to FAQ it should reflect in FAQ. else, completely gone."

So: an answered ClinicQuestion and a done PatientMessage drop out of the
Dashboard list responses. The rows STAY in the database (healthcare record —
the answer text is history), they are just no longer surfaced. RULE 1: the
filtered lists remain branch-scoped.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.main import app
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import (
    Branch, ClinicQuestion, Organization, Patient, PatientMessage,
)


def _as_user(branch_id, org_id, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@c.com", role=role,
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


async def _clinic(db, wa):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099055",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number=wa)
    db.add(br)
    await db.commit()
    return org_id, br


async def _question(db, br, text, phone="+919876540001"):
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name="Vinay", phone=phone)
    db.add(p)
    await db.flush()
    q = ClinicQuestion(
        id=uuid.uuid4(), branch_id=br.id, question=text,
        caller_last4=phone[-4:], patient_id=p.id, caller_phone=phone,
    )
    db.add(q)
    await db.commit()
    return q


@pytest.mark.asyncio
async def test_answered_question_leaves_the_dashboard_but_stays_in_db(db):
    org_id, br = await _clinic(db, "+910000000301")
    open_q = await _question(db, br, "Do you take cash?")
    done_q = await _question(db, br, "Do you do root canal in one sitting?",
                             phone="+919876540002")

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/questions/{done_q.id}/answer",
                json={"answer": "Yes, single sitting RCT is done here.",
                      "add_to_faq": False},
            )
            assert r.status_code == 200, r.text

            body = (await ac.get(f"/branches/{br.id}/questions")).json()
            ids = [row["id"] for row in body["questions"]]
            assert ids == [str(open_q.id)], "answered question must be gone"
            assert body["pending"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # NOT hard-deleted: the answer is a record.
    kept = (await db.execute(
        select(ClinicQuestion).where(ClinicQuestion.id == done_q.id)
    )).scalar_one()
    assert kept.answer.startswith("Yes, single sitting RCT")


@pytest.mark.asyncio
async def test_faq_ticked_answer_lands_in_the_branch_faq(db):
    """The tick is the ONLY way an answered question survives on the UI — it
    must actually write into Branch.faq (what the voice agent reads)."""
    org_id, br = await _clinic(db, "+910000000302")
    q = await _question(db, br, "Are you open on Sunday?", phone="+919876540003")

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/questions/{q.id}/answer",
                json={"answer": "Yes, 10am to 1pm.", "add_to_faq": True},
            )
            assert r.status_code == 200, r.text
            assert r.json()["added_to_faq"] is True

            faq = (await ac.get(f"/branches/{br.id}/faq")).json()
            assert {"q": "Are you open on Sunday?", "a": "Yes, 10am to 1pm."} in faq["faq"]
            # …and it is off the dashboard all the same.
            assert (await ac.get(f"/branches/{br.id}/questions")).json()["questions"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    branch = await db.get(Branch, br.id)
    await db.refresh(branch)
    assert branch.faq == [{"q": "Are you open on Sunday?", "a": "Yes, 10am to 1pm."}]


@pytest.mark.asyncio
async def test_done_message_leaves_the_dashboard_but_stays_in_db(db):
    org_id, br = await _clinic(db, "+910000000303")
    open_m = PatientMessage(branch_id=br.id, caller_phone="+919000101010",
                            message="Tell doctor I will be late")
    done_m = PatientMessage(branch_id=br.id, caller_phone="+919000202020",
                            message="Call me about my bill")
    db.add_all([open_m, done_m])
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.patch(f"/branches/{br.id}/messages/{done_m.id}")
            assert r.status_code == 200, r.text

            body = (await ac.get(f"/branches/{br.id}/messages")).json()
            ids = [row["id"] for row in body["messages"]]
            assert ids == [str(open_m.id)], "resolved message must be gone"
            assert body["pending"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    kept = (await db.execute(
        select(PatientMessage).where(PatientMessage.id == done_m.id)
    )).scalar_one()
    assert kept.status == "done" and kept.resolved_at is not None


# ── pre-ll35 questions: recover the number so the callback actually fires ────
#
# Vinay 2026-08-03: "call is not getting triggered even after question answered
# here by doctor." Those rows predate the caller_phone column (ll35) — they
# carry only caller_last4, so every answer landed on "unreachable".


async def _legacy_question(db, br, text, last4, patient_id=None):
    """A question as it exists in the pre-ll35 backlog: no caller_phone."""
    q = ClinicQuestion(
        id=uuid.uuid4(), branch_id=br.id, question=text,
        caller_last4=last4, patient_id=patient_id, caller_phone=None,
    )
    db.add(q)
    await db.commit()
    return q


async def _patient(db, br, name, phone):
    p = Patient(id=uuid.uuid4(), branch_id=br.id, name=name, phone=phone)
    db.add(p)
    await db.commit()
    return p


async def _answer(ac, br, q, answer="Yes, we do."):
    return await ac.post(f"/branches/{br.id}/questions/{q.id}/answer",
                         json={"answer": answer, "add_to_faq": False})


@pytest.mark.asyncio
async def test_legacy_question_recovers_phone_from_linked_patient(db):
    org_id, br = await _clinic(db, "+910000000306")
    p = await _patient(db, br, "Vinay", "+919876547554")
    q = await _legacy_question(db, br, "Do you do implants?", "7554", p.id)

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await _answer(ac, br, q)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "answered"
            assert r.json()["callback_queued"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    await db.refresh(q)
    assert q.caller_phone == "+919876547554"  # persisted for the callback job
    assert q.status == "answered"


@pytest.mark.asyncio
async def test_legacy_question_recovers_phone_from_unique_last4_match(db):
    """No patient_id — but exactly one patient in the branch ends with those
    four digits, so the number is unambiguous."""
    org_id, br = await _clinic(db, "+910000000307")
    await _patient(db, br, "Vinay", "+919876541234")
    await _patient(db, br, "Ravi", "+919876549999")  # different last-4
    q = await _legacy_question(db, br, "Do you open early?", "1234")

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await _answer(ac, br, q)
            assert r.status_code == 200, r.text
            assert r.json()["callback_queued"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    await db.refresh(q)
    assert q.caller_phone == "+919876541234"


@pytest.mark.asyncio
async def test_ambiguous_last4_stays_unreachable_and_stores_no_number(db):
    """Two DIFFERENT numbers share the last four digits — dialing the wrong one
    would read patient A's answer to patient B. Fail closed."""
    org_id, br = await _clinic(db, "+910000000308")
    await _patient(db, br, "Vinay", "+919876545678")
    await _patient(db, br, "Ravi", "+919812345678")
    q = await _legacy_question(db, br, "Do you do whitening?", "5678")

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await _answer(ac, br, q)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "unreachable"
            assert r.json()["callback_queued"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    await db.refresh(q)
    assert q.caller_phone is None
    assert q.answer == "Yes, we do."  # the answer is still recorded


@pytest.mark.asyncio
async def test_family_sharing_one_phone_is_not_ambiguous(db):
    """Several patient rows can share one phone (family bookings). That is one
    delivery address, not an ambiguity — recovery still works."""
    org_id, br = await _clinic(db, "+910000000309")
    await _patient(db, br, "Vinay", "+919876540077")
    await _patient(db, br, "Vinay's mother", "+919876540077")
    q = await _legacy_question(db, br, "Is parking available?", "0077")

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            assert (await _answer(ac, br, q)).json()["callback_queued"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    await db.refresh(q)
    assert q.caller_phone == "+919876540077"


@pytest.mark.asyncio
async def test_rule1_last4_never_recovered_from_another_branch(db):
    """RULE 1: the only patient with that last-4 belongs to another clinic —
    the number must NOT be borrowed. Stays unreachable."""
    _org_a, br_a = await _clinic(db, "+910000000310")
    org_b, br_b = await _clinic(db, "+910000000311")
    await _patient(db, br_a, "Clinic A patient", "+919876544321")
    q = await _legacy_question(db, br_b, "Do you do braces?", "4321")

    app.dependency_overrides[get_current_user] = lambda: _as_user(br_b.id, org_b)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await _answer(ac, br_b, q)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "unreachable"
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    await db.refresh(q)
    assert q.caller_phone is None


@pytest.mark.asyncio
async def test_recovered_question_is_actually_dialed_by_the_callback_job(db):
    """End to end: the recovery must reach the job that places the call."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    org_id, br = await _clinic(db, "+910000000312")
    p = await _patient(db, br, "Vinay", "+919876543311")
    q = await _legacy_question(db, br, "Do you do RCT?", "3311", p.id)

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            assert (await _answer(ac, br, q)).status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    from backend.jobs.question_callback_caller import run_question_callbacks

    with patch("backend.jobs.question_callback_caller._dispatch",
               new=AsyncMock(return_value=True)) as disp:
        n = await run_question_callbacks(
            now=datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc)
        )
    assert n == 1 and disp.await_count == 1
    await db.refresh(q)
    assert q.status == "called"


@pytest.mark.asyncio
async def test_rule1_other_clinic_never_sees_these_lists(db):
    """RULE 1: filtering the lists must not widen them — clinic B still gets
    403 on clinic A's questions and messages."""
    _org_a, br_a = await _clinic(db, "+910000000304")
    org_b, br_b = await _clinic(db, "+910000000305")
    await _question(db, br_a, "Private to clinic A", phone="+919876540004")
    db.add(PatientMessage(branch_id=br_a.id, caller_phone="+919000303030",
                          message="Private to clinic A"))
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br_b.id, org_b)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            assert (await ac.get(f"/branches/{br_a.id}/questions")).status_code == 403
            assert (await ac.get(f"/branches/{br_a.id}/messages")).status_code == 403
            # Their own lists carry nothing of clinic A's.
            assert (await ac.get(f"/branches/{br_b.id}/questions")).json()["questions"] == []
            assert (await ac.get(f"/branches/{br_b.id}/messages")).json()["messages"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
