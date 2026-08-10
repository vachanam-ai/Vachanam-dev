"""WA T5-T7: webhook handshake + HMAC + dispatch; button flows; chat intents.

RULE 1 focus: crossed-branch events and smuggled token ids must never touch
another clinic's data.
"""
import hashlib
import hmac as hmac_mod
import json
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import (
    Branch, Doctor, Organization, Patient, PatientMessage, Rating, Token,
)
from backend.services import wa_actions, wa_chat, wa_service

SECRET = "app-secret-test"
VERIFY = "verify-token-test"


def _sig(raw: bytes) -> str:
    return "sha256=" + hmac_mod.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def wa_env(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", SECRET, raising=False)
    monkeypatch.setattr(settings, "meta_webhook_verify_token", VERIFY, raising=False)
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    sent = []

    async def _fake_text(branch, to, text, plan=None):
        sent.append({"branch": str(branch.id), "to": to, "text": text})
        return True

    monkeypatch.setattr(wa_service, "send_text", _fake_text)
    return sent


async def _setup(db, plan="clinic"):
    org = Organization(
        name="WOrg", owner_phone="+919000700020",
        owner_email=f"wh-{uuid.uuid4().hex[:6]}@test.com", plan=plan, status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="WBranch", clinic_phone="+914012345678",
        whatsapp_number=f"+9155{str(uuid.uuid4().int)[:8]}", status="active",
        wa_phone_number_id=str(uuid.uuid4().int)[:12],
        wa_status="connected",
    )
    db.add(b)
    await db.flush()
    doc = Doctor(branch_id=b.id, name="Dr W", booking_type="token")
    pat = Patient(branch_id=b.id, name="Pat", phone="+919000000042")
    db.add_all([doc, pat])
    await db.flush()
    tok = Token(
        branch_id=b.id, doctor_id=doc.id, patient_id=pat.id,
        date=date.today(), token_number=2, source="voice", status="confirmed",
    )
    db.add(tok)
    await db.commit()
    return b, pat, tok


def _event(phone_number_id, msg):
    return {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": phone_number_id},
            "messages": [msg],
        }}]}],
    }


# ── handshake + HMAC ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_handshake(client, wa_env):
    r = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY,
                "hub.challenge": "42abc"},
    )
    assert r.status_code == 200 and r.text == "42abc"
    r2 = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                "hub.challenge": "x"},
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_bad_signature_403(client, wa_env):
    raw = json.dumps({"entry": []}).encode()
    r = await client.post(
        "/webhooks/whatsapp", content=raw,
        headers={"X-Hub-Signature-256": "sha256=deadbeef",
                 "Content-Type": "application/json"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unknown_receiver_dropped_200(client, db, wa_env):
    raw = json.dumps(_event("999999", {"id": "m1", "type": "text", "from": "919",
                                       "text": {"body": "hi"}})).encode()
    r = await client.post(
        "/webhooks/whatsapp", content=raw,
        headers={"X-Hub-Signature-256": _sig(raw),
                 "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert wa_env == []  # nothing sent, nothing crashed


# ── rating buttons ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rating_button_stores_once(client, db, wa_env):
    b, pat, tok = await _setup(db)
    payload = f"rate:{tok.id}:4"
    for mid in ("m-r1", "m-r2"):  # second = different message, same token
        raw = json.dumps(_event(b.wa_phone_number_id, {
            "id": mid, "type": "button", "from": "919000000042",
            "button": {"payload": payload},
        })).encode()
        r = await client.post(
            "/webhooks/whatsapp", content=raw,
            headers={"X-Hub-Signature-256": _sig(raw),
                     "Content-Type": "application/json"},
        )
        assert r.status_code == 200
    from sqlalchemy import select

    rows = (await db.execute(select(Rating).where(Rating.token_id == tok.id))).scalars().all()
    assert len(rows) == 1 and rows[0].score == 4
    assert any("Thank you" in s["text"] for s in wa_env)


@pytest.mark.asyncio
async def test_smuggled_token_from_other_branch_rejected(db, wa_env):
    b1, _, tok1 = await _setup(db)
    b2, _, _ = await _setup(db)
    # branch B2's webhook delivering B1's token id → generic reply, no rating
    await wa_actions.dispatch_button(db, b2, "clinic", "919000000042", f"rate:{tok1.id}:5")
    from sqlalchemy import select

    rows = (await db.execute(select(Rating))).scalars().all()
    assert rows == []
    # The reply must be generic — never confirm the token exists or leak whose
    # it is (RULE 1). It used to say "call us"; that is banned in WhatsApp now
    # (Vinay 2026-08-02), so assert the GUARANTEE rather than the sentence.
    reply = wa_env[-1]["text"].lower()
    assert reply, "must still answer — RULE 8, no dead ends"
    assert "call us" not in reply and "call the clinic" not in reply
    assert str(tok1.id) not in reply and "rating" not in reply


# ── reschedule/cancel buttons (day-1 callback flow) ──────────────────────────

@pytest.mark.asyncio
async def test_reschedule_button_creates_dashboard_message(db, wa_env):
    b, pat, tok = await _setup(db)
    await wa_actions.dispatch_button(db, b, "clinic", "919000000042", f"rs:{tok.id}")
    from sqlalchemy import select

    msgs = (await db.execute(select(PatientMessage))).scalars().all()
    assert len(msgs) == 1
    assert "reschedule" in msgs[0].message
    assert msgs[0].branch_id == b.id
    reply = wa_env[-1]["text"]
    # Honest: the clinic still has to confirm — the reply must never claim the
    # booking was already changed (nothing was written). It used to promise a
    # phone call back; sending a patient to a phone is banned in WhatsApp now
    # (Vinay 2026-08-02), so the invitation is to reply in chat instead.
    assert "changed" not in reply.lower() and "rescheduled" not in reply.lower()
    assert "call us" not in reply.lower() and "call you" not in reply.lower()
    assert "reply here" in reply.lower()


# ── chat intents (Gemini mocked) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_location_intent(db, wa_env, monkeypatch):
    b, _, _ = await _setup(db)
    b.address = "12 MG Road, Hyderabad"
    await db.commit()

    async def _fake_gemini(prompt):
        return json.dumps({"intent": "location", "answer": ""})

    monkeypatch.setattr(wa_chat, "_call_gemini", _fake_gemini)
    await wa_chat.handle_text(db, b, "clinic", "919000000042", "where is the clinic?")
    assert "maps.google.com" in wa_env[-1]["text"]


@pytest.mark.asyncio
async def test_chat_medical_goes_to_the_doctor_never_triaged(db, wa_env, monkeypatch):
    """WA MVP1 Task 6 (Vinay 2026-08-02): a symptom question is `ask_doctor`
    — it reaches the doctor via ClinicQuestion, it is NEVER answered by the
    bot, and "call us" is banned platform-wide, so it must not appear here
    either."""
    from sqlalchemy import select

    from backend.models.schema import ClinicQuestion

    b, _, _ = await _setup(db)

    async def _fake_gemini(prompt):
        # RULE 7: prompt itself must forbid medical judgment. Case-insensitive
        # — the prompt is hand-edited and capitalises its rules for emphasis;
        # a case-sensitive assert here failed INSIDE the stub, was swallowed by
        # handle_text's fallback, and showed up as a missing ClinicQuestion row
        # rather than as the wording mismatch it actually was.
        assert "never give medical advice" in prompt.lower()
        return json.dumps({"intent": "ask_doctor", "answer": ""})

    monkeypatch.setattr(wa_chat, "_call_gemini", _fake_gemini)
    await wa_chat.handle_text(db, b, "clinic", "919000000042", "my tooth pains, which medicine?")

    reply = wa_env[-1]["text"].lower()
    assert "call us" not in reply and "call the clinic" not in reply
    for w in ("serious", "urgent", "you should", "medicine"):
        assert w not in reply
    q = (await db.execute(select(ClinicQuestion))).scalars().one()
    assert q.branch_id == b.id and "tooth" in q.question.lower()


@pytest.mark.asyncio
async def test_chat_gemini_down_static_fallback(db, wa_env, monkeypatch):
    """RULE 8 — no dead end. Also banned (Vinay 2026-08-02): "call us"."""
    b, _, _ = await _setup(db)

    async def _boom(prompt):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(wa_chat, "_call_gemini", _boom)
    await wa_chat.handle_text(db, b, "clinic", "919000000042", "hello")
    reply = wa_env[-1]["text"].lower()
    assert reply  # a reply was sent — never a dead end
    assert "call us" not in reply and "call the clinic" not in reply


# ── the WABA id arrives on the webhook, nowhere else ─────────────────────────

@pytest.mark.asyncio
async def test_the_waba_id_is_learned_from_the_webhook(client, db, wa_env):
    """Vinay 2026-08-05 got all 7 templates approved and still saw nothing send.

    Template discovery lists /{waba_id}/message_templates, but a branch linked
    by phone_number_id alone has wa_waba_id NULL — and the Graph API will not
    walk phone_number_id -> WABA (`whatsapp_business_account` is not a field on
    the phone node). The ONLY place that id reaches us is `entry.id` on the
    webhook, which was being discarded. So every template send resolved to "no
    template for this purpose" and silently skipped.
    """
    from sqlalchemy import select

    from backend.models.schema import Branch

    b, _pat, _tok = await _setup(db)
    b.wa_waba_id = None
    # Capture BEFORE commit — commit expires the ORM object, and a later
    # attribute read would be a sync lazy-load on the async session.
    bid, pnid = b.id, b.wa_phone_number_id
    await db.commit()

    payload = _event(pnid,
                     {"id": "m-waba", "type": "text", "from": "919000000042",
                      "text": {"body": "hi"}})
    payload["entry"][0]["id"] = "555000111222"
    raw = json.dumps(payload).encode()
    r = await client.post(
        "/webhooks/whatsapp", content=raw,
        headers={"X-Hub-Signature-256": _sig(raw), "Content-Type": "application/json"},
    )
    assert r.status_code == 200

    db.expire_all()
    fresh = (await db.execute(select(Branch).where(Branch.id == bid))).scalar_one()
    assert fresh.wa_waba_id == "555000111222"


@pytest.mark.asyncio
async def test_a_known_waba_id_is_never_overwritten(client, db, wa_env):
    """Only ever fills a hole. A branch already connected keeps its id even if
    a stray webhook arrives claiming another."""
    from sqlalchemy import select

    from backend.models.schema import Branch

    b, _pat, _tok = await _setup(db)
    b.wa_waba_id = "111aaa"
    bid, pnid = b.id, b.wa_phone_number_id
    await db.commit()

    payload = _event(pnid,
                     {"id": "m-waba2", "type": "text", "from": "919000000042",
                      "text": {"body": "hi"}})
    payload["entry"][0]["id"] = "999zzz"
    raw = json.dumps(payload).encode()
    await client.post(
        "/webhooks/whatsapp", content=raw,
        headers={"X-Hub-Signature-256": _sig(raw), "Content-Type": "application/json"},
    )

    db.expire_all()
    fresh = (await db.execute(select(Branch).where(Branch.id == bid))).scalar_one()
    assert fresh.wa_waba_id == "111aaa"
