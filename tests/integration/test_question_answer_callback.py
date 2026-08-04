"""Unanswered caller questions → doctor answers → patient gets a callback.

Vinay 2026-08-02: a question the AI could not answer is logged for the doctor
WITH who asked it; the doctor answers it on the dashboard and chooses whether
it joins the FAQ. Either choice must still result in a callback that reads the
answer out. Covers: listing + identity, FAQ append on opt-in, NO append on
opt-out (callback either way), RULE 1 cross-branch isolation, and the job's
dispatch/retry state machine.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.main import app
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import Branch, ClinicQuestion, Organization, Patient


def _as_user(branch_id, org_id, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@c.com", role=role,
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


async def _seed(db, wa, phone="+919876547554"):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099077",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number=wa)
    db.add(br)
    await db.flush()
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="Vinay", phone=phone)
    db.add(pat)
    await db.flush()
    q = ClinicQuestion(
        id=uuid.uuid4(), branch_id=br.id,
        question="Do you do root canal in one sitting?",
        caller_last4=phone[-4:], patient_id=pat.id, caller_phone=phone,
    )
    db.add(q)
    await db.commit()
    return org_id, br, pat, q


@pytest.mark.asyncio
async def test_list_shows_who_asked(db):
    org_id, br, pat, q = await _seed(db, "+910000000091")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get(f"/branches/{br.id}/questions")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["pending"] == 1
            row = body["questions"][0]
            assert row["question"] == "Do you do root canal in one sitting?"
            assert row["patient_name"] == "Vinay"        # name shown
            assert row["caller_phone"] == pat.phone      # number shown
            assert row["answer"] is None and row["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_answer_with_faq_opt_in_appends_and_queues_callback(db):
    org_id, br, _pat, q = await _seed(db, "+910000000092")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/questions/{q.id}/answer",
                json={"answer": "Yes, single sitting RCT is done here.", "add_to_faq": True},
            )
            assert r.status_code == 200, r.text
            assert r.json()["added_to_faq"] is True
            assert r.json()["callback_queued"] is True

            faq = (await ac.get(f"/branches/{br.id}/faq")).json()
            assert faq["faq"] == [{
                "q": "Do you do root canal in one sitting?",
                "a": "Yes, single sitting RCT is done here.",
            }]
            # Answered questions drop out of the Settings "asked" list.
            assert faq["asked"] == []
    finally:
        app.dependency_overrides.clear()

    await db.refresh(q)
    assert q.status == "answered"        # queued for the callback job
    assert q.added_to_faq is True


@pytest.mark.asyncio
async def test_answer_without_faq_still_queues_callback(db):
    """The doctor said "don't add to FAQ" — the FAQ stays empty, but the
    patient is still called back with the answer."""
    org_id, br, _pat, q = await _seed(db, "+910000000093")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/questions/{q.id}/answer",
                json={"answer": "Depends on the tooth — the doctor will tell you.",
                      "add_to_faq": False},
            )
            assert r.status_code == 200, r.text
            assert r.json()["added_to_faq"] is False
            assert r.json()["callback_queued"] is True
            assert (await ac.get(f"/branches/{br.id}/faq")).json()["faq"] == []
    finally:
        app.dependency_overrides.clear()

    await db.refresh(q)
    assert q.status == "answered"
    assert q.answer.startswith("Depends on the tooth")


@pytest.mark.asyncio
async def test_answering_another_branchs_question_is_404(db):
    """RULE 1: a question id from another clinic must not be answerable."""
    org_a, br_a, _p, q_a = await _seed(db, "+910000000094")
    _org_b, br_b, _p2, _q_b = await _seed(db, "+910000000095", phone="+919876500011")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br_b.id, _org_b)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br_b.id}/questions/{q_a.id}/answer",
                json={"answer": "leak", "add_to_faq": True},
            )
            assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
    await db.refresh(q_a)
    assert q_a.answer is None
    assert (await db.get(Branch, br_b.id)).faq in (None, [])


@pytest.mark.asyncio
async def test_answer_without_phone_is_unreachable_not_queued(db):
    org_id, br, _pat, q = await _seed(db, "+910000000096")
    q.caller_phone = None
    q.patient_id = None
    # caller_last4 must go too, or the pre-ll35 recovery added 2026-08-03 finds
    # the seeded patient by their last four digits and correctly queues a call.
    # This test is about having genuinely NOTHING to dial.
    q.caller_last4 = None
    await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/questions/{q.id}/answer",
                json={"answer": "Yes we do.", "add_to_faq": True},
            )
            assert r.status_code == 200, r.text
            assert r.json()["callback_queued"] is False
            assert r.json()["added_to_faq"] is True   # FAQ still grows
    finally:
        app.dependency_overrides.clear()
    await db.refresh(q)
    assert q.status == "unreachable"


@pytest.mark.asyncio
async def test_doctor_login_may_answer_and_push_to_faq(db):
    """Vinay 2026-08-02: doctors answer these even though the Settings FAQ
    editor stays owner-only — they are the ones who know the answer."""
    org_id, br, _pat, q = await _seed(db, "+910000000090")
    app.dependency_overrides[get_current_user] = lambda: _as_user(
        br.id, org_id, role="doctor"
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            assert (await ac.get(f"/branches/{br.id}/questions")).status_code == 200
            r = await ac.post(
                f"/branches/{br.id}/questions/{q.id}/answer",
                json={"answer": "Usually yes, in one sitting.", "add_to_faq": True},
            )
            assert r.status_code == 200, r.text
            assert r.json()["added_to_faq"] is True
    finally:
        app.dependency_overrides.clear()


# ── the callback job ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_job_dispatches_answered_question_and_marks_called(db):
    from backend.jobs.question_callback_caller import run_question_callbacks

    _org, br, _pat, q = await _seed(db, "+910000000097")
    q.answer = "Yes, single sitting RCT is done here."
    q.answered_at = datetime.now(timezone.utc)
    q.status = "answered"
    await db.commit()

    with patch("backend.jobs.question_callback_caller._dispatch",
               new=AsyncMock(return_value=True)) as disp:
        n = await run_question_callbacks(
            now=datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
        )
    assert n == 1
    assert disp.await_count == 1
    await db.refresh(q)
    assert q.status == "called"
    assert q.call_attempts == 1


@pytest.mark.asyncio
async def test_job_retries_until_attempts_exhausted(db):
    """A dispatch nobody picks up leaves the row queued (self-healing), and
    only gives up after MAX_ATTEMPTS — never marked delivered."""
    from backend.jobs import question_callback_caller as job

    _org, br, _pat, q = await _seed(db, "+910000000098")
    q.answer = "Yes."
    q.status = "answered"
    await db.commit()

    with patch.object(job, "_dispatch", new=AsyncMock(return_value=False)):
        for attempt in range(1, job.MAX_ATTEMPTS + 1):
            await job.run_question_callbacks(
                now=datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
            )
            await db.refresh(q)
            assert q.call_attempts == attempt
            expected = "unreachable" if attempt >= job.MAX_ATTEMPTS else "answered"
            assert q.status == expected


@pytest.mark.asyncio
async def test_job_never_dials_outside_calling_hours(db):
    from backend.jobs import question_callback_caller as job

    _org, br, _pat, q = await _seed(db, "+910000000099")
    q.answer = "Yes."
    q.status = "answered"
    await db.commit()

    with patch.object(job, "_dispatch", new=AsyncMock(return_value=True)) as disp:
        # 03:00 IST
        n = await job.run_question_callbacks(
            now=datetime(2026, 8, 2, 3, 0, tzinfo=job.IST)
        )
    assert n == 0 and disp.await_count == 0
    await db.refresh(q)
    assert q.status == "answered"


def test_compose_message_carries_question_and_answer():
    from backend.jobs.question_callback_caller import compose_message

    msg = compose_message("Do you do root canal in one sitting?", "Yes, we do.")
    assert "root canal in one sitting" in msg
    assert "Yes, we do." in msg


# ── a question can be dropped without answering (Vinay 2026-08-04) ───────────

@pytest.mark.asyncio
async def test_dismiss_drops_the_question_without_contacting_the_caller(db):
    """Vinay: "some sarcastic questions are also dropping... include option to
    delete question without answering, which will never go to user."

    Answering was the only exit, and answering PHONES the caller — so a joke
    could only be cleared by calling someone back about it.
    """
    org_id, br, _pat, q = await _seed(db, "+910000000097")
    qid = q.id  # capture before expire_all — a later attribute read would be a
    # sync lazy-load on the async session (MissingGreenlet)
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/branches/{br.id}/questions/{q.id}/dismiss")
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "dismissed"

            # Off the desk...
            listed = await ac.get(f"/branches/{br.id}/questions")
            assert listed.json()["questions"] == []
            assert listed.json()["pending"] == 0
            # ...and out of the Settings backlog too.
            faq = await ac.get(f"/branches/{br.id}/faq")
            assert faq.json()["asked"] == []

        db.expire_all()
        row = (await db.execute(
            select(ClinicQuestion).where(ClinicQuestion.id == qid)
        )).scalar_one()
        assert row.status == "dismissed"
        # No answer means the callback job — which only ever selects
        # status == 'answered' — can never dial this person.
        assert row.answer is None
        assert row.answered_at is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_an_answered_question_cannot_be_dismissed(db):
    """Once answered the callback is queued or already made; dismissing would
    imply we can unsend it."""
    org_id, br, _pat, q = await _seed(db, "+910000000098")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            ok = await ac.post(
                f"/branches/{br.id}/questions/{q.id}/answer",
                json={"answer": "Yes, usually one sitting.", "add_to_faq": False},
            )
            assert ok.status_code == 200, ok.text
            r = await ac.post(f"/branches/{br.id}/questions/{q.id}/dismiss")
            assert r.status_code == 409, r.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dismissing_another_branchs_question_is_404(db):
    """RULE 1: the id alone must never be enough."""
    org_a, br_a, _pa, q_a = await _seed(db, "+910000000099")
    _org_b, br_b, _pb, _q_b = await _seed(db, "+910000000100", phone="+919876500001")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br_b.id, _org_b)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/branches/{br_b.id}/questions/{q_a.id}/dismiss")
            assert r.status_code == 404, r.text
    finally:
        app.dependency_overrides.clear()
