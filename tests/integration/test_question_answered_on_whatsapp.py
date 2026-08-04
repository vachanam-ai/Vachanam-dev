"""Answer a patient on the channel they chose.

Vinay 2026-08-04: "questions asked in whatsapp should get whatsapp reply after
getting confirmation from clinic. not call. because, those people whatsapp
clinic because they don't want to talk."

Every answered ClinicQuestion used to be handed to the callback job, so someone
who deliberately typed instead of calling got their phone rung. Right answer,
wrong delivery.

The fallback matters as much as the feature: Meta only allows free-form text
inside 24 hours of the patient's last message, and no clinic has an
answer-shaped approved template. So an undeliverable WhatsApp reply must leave
the question queued for the phone callback rather than stranding the patient.
"""
import uuid

import pytest
from sqlalchemy import select

from backend.models.schema import Branch, ClinicQuestion, Organization
from backend.services import wa_service, wa_whatsapp_answer


async def _clinic(db):
    org = Organization(
        name="AnsOrg", owner_phone="+919000700044",
        owner_email=f"ans-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="Ans Clinic", status="active",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
        wa_phone_number_id="pnid-ans",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _question(db, br, *, channel="whatsapp", phone="919876500055"):
    q = ClinicQuestion(
        branch_id=br.id, question="Is there any plastic surgeon in your clinic?",
        caller_last4=phone[-4:], caller_phone=phone, channel=channel,
    )
    db.add(q)
    await db.commit()
    return q


# ── delivery ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_answer_goes_out_over_whatsapp(db, monkeypatch):
    _org, br = await _clinic(db)
    q = await _question(db, br)
    sent = []

    async def fake_send(branch, to, text, plan=None):
        sent.append({"to": to, "text": text})
        return True

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)
    monkeypatch.setattr(wa_service, "send_text", fake_send)

    ok = await wa_whatsapp_answer.reply(db, br.id, q, "Yes, Dr Mehta consults on Fridays.")

    assert ok is True
    assert len(sent) == 1
    assert "Dr Mehta consults on Fridays" in sent[0]["text"]


@pytest.mark.asyncio
async def test_the_original_question_is_quoted_back(db, monkeypatch):
    """The doctor may answer hours later; "Yes, we do" alone is meaningless
    by then."""
    _org, br = await _clinic(db)
    q = await _question(db, br)
    sent = []

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def fake_send(branch, to, text, plan=None):
        sent.append(text)
        return True

    monkeypatch.setattr(wa_service, "send_text", fake_send)
    await wa_whatsapp_answer.reply(db, br.id, q, "Yes.")

    assert "plastic surgeon" in sent[0]


def test_a_very_long_question_is_trimmed_not_dumped():
    out = wa_whatsapp_answer.compose("x" * 400, "Yes.")
    assert "…" in out and len(out) < 250


def test_an_answer_with_no_question_still_reads_fine():
    assert wa_whatsapp_answer.compose("", "We open at 9 am.") == "We open at 9 am."


# ── the fallback ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_undelivered_reply_reports_false_so_the_call_still_happens(
    db, monkeypatch
):
    """Meta's 24-hour window closes. The patient must still get their answer,
    by phone, rather than silence."""
    _org, br = await _clinic(db)
    q = await _question(db, br)

    async def fake_send(branch, to, text, plan=None):
        return False  # outside the service window

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)
    monkeypatch.setattr(wa_service, "send_text", fake_send)

    assert await wa_whatsapp_answer.reply(db, br.id, q, "Yes.") is False


@pytest.mark.asyncio
async def test_whatsapp_being_down_reports_false_rather_than_raising(db, monkeypatch):
    _org, br = await _clinic(db)
    q = await _question(db, br)

    async def boom(*a, **k):
        raise RuntimeError("meta down")

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)
    monkeypatch.setattr(wa_service, "send_text", boom)

    assert await wa_whatsapp_answer.reply(db, br.id, q, "Yes.") is False


@pytest.mark.asyncio
async def test_a_question_with_no_number_is_not_attempted(db):
    _org, br = await _clinic(db)
    q = await _question(db, br)
    q.caller_phone = None
    await db.commit()

    assert await wa_whatsapp_answer.reply(db, br.id, q, "Yes.") is False


# ── channel + status wiring ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_whatsapp_question_is_recorded_as_whatsapp(db):
    """wa_agent stamps the channel; without it the answer would be phoned."""
    from backend.services import wa_agent

    _org, br = await _clinic(db)
    await wa_agent.WaTools(db, br, "919876500055", "clinic").record_question_for_doctor(
        question="do you do root canals?"
    )
    row = (
        await db.execute(select(ClinicQuestion).where(ClinicQuestion.branch_id == br.id))
    ).scalars().one()
    assert row.channel == "whatsapp"


def test_the_callback_job_only_dials_answered_never_replied():
    """"replied" is terminal — the answer already reached the patient on
    WhatsApp, and dialling them anyway is the exact behaviour being removed."""
    import inspect

    from backend.jobs import question_callback_caller

    src = inspect.getsource(question_callback_caller)
    assert 'ClinicQuestion.status == "answered"' in src
    assert '"replied"' not in src


def test_voice_questions_still_default_to_a_callback():
    """The default must stay "voice", so a call-originated question behaves
    exactly as before."""
    col = ClinicQuestion.__table__.columns["channel"]
    assert col.default.arg == "voice"
