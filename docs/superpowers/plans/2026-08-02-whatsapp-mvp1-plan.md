# WhatsApp MVP1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a real clinic number on WhatsApp answering patients this week — outbound templates, FAQ replies, cancel/reschedule, and unknown questions routed to the doctor — on a per-branch credential seam that makes the later Tech Provider switch a flag flip.

**Architecture:** Keep every existing send/webhook/template path. Add (a) per-branch WhatsApp credentials on `branches` with a resolver that falls back to the platform token while `wa_token_enc` is NULL (bridge mode), (b) a WhatsApp-only prompt module separate from the voice prompt, (c) the unknown-question loop shipped for voice on 2026-08-02 reused for chat. No new page, no conversational booking (that is MVP4).

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Alembic, httpx + tenacity, Fernet (`backend/services/crypto.py`), Gemini via `support_bot._call_gemini`, React 18 + TanStack Query.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-02-whatsapp-hub-cross-channel-design.md` — the decisions table is binding. MVP1 scope is §9 "MVP1".
- **MVP1 does not book over chat.** A new-booking request still points at the phone line. Do not add booking logic here (§0.5).
- D5: templates are **English only** — `template_lang()` returns the constant `"en"`.
- D6: free-text replies **mirror the patient's language**.
- D14: **no patient message body is ever written to Postgres.** Not in logs either.
- RULE 1: every query branch-scoped; one branch's token may never send on another branch's number.
- RULE 4: a WhatsApp failure never raises into a booking path — every public send returns `bool`.
- RULE 5: inbound branch = receiving `phone_number_id`, never the sender.
- RULE 9: logs carry `to_last4`, template name, branch id — never body text.
- Plan gate `WHATSAPP_PLANS = frozenset({"clinic", "multi"})` stays the single source.
- Alembic head at plan time: `ll35_question_answer`. New revision goes after it.
- Full suite (`python -m pytest -q --ignore=tests/e2e`) must be green before every push. Baseline: 1,517 passed, 2 skipped.

---

### Task 1: Branch WhatsApp credential columns

**Files:**
- Modify: `backend/models/schema.py` (class `Branch`, after `wa_phone_number_id` at ~line 110)
- Create: `alembic/versions/mm36_branch_wa_credentials.py`
- Test: `tests/integration/test_wa_branch_credentials.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Branch.wa_waba_id: str | None`, `Branch.wa_token_enc: str | None`, `Branch.wa_status: str` (`none` | `connected` | `disconnected` | `error`), `Branch.wa_connected_at: datetime | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_wa_branch_credentials.py
"""MVP1 Task 1: per-branch WhatsApp credentials (bridge mode → Tech Provider seam)."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.schema import Branch, Organization


async def _org(db):
    org = Organization(
        id=uuid.uuid4(), name="Cred Org", owner_phone="+919000012345",
        owner_email=f"cred-{uuid.uuid4()}@c.test", plan="clinic",
    )
    db.add(org)
    await db.flush()
    return org


@pytest.mark.asyncio
async def test_new_branch_defaults_to_unconnected(db):
    org = await _org(db)
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="B1",
                whatsapp_number="+910000000101")
    db.add(br)
    await db.commit()
    await db.refresh(br)
    assert br.wa_status == "none"
    assert br.wa_waba_id is None
    assert br.wa_token_enc is None
    assert br.wa_connected_at is None


@pytest.mark.asyncio
async def test_one_waba_id_cannot_serve_two_branches(db):
    """RULE 1: a WABA belongs to exactly one branch."""
    org = await _org(db)
    a = Branch(id=uuid.uuid4(), org_id=org.id, name="A",
               whatsapp_number="+910000000102", wa_waba_id="55501")
    db.add(a)
    await db.commit()
    b = Branch(id=uuid.uuid4(), org_id=org.id, name="B",
               whatsapp_number="+910000000103", wa_waba_id="55501")
    db.add(b)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_wa_branch_credentials.py -q`
Expected: FAIL — `AttributeError`/`TypeError` on `wa_status` (column does not exist).

- [ ] **Step 3: Add the model columns**

In `backend/models/schema.py`, directly below `wa_phone_number_id`:

```python
    # Per-branch WhatsApp credentials (spec 2026-08-02 §6, D10). NULL token =
    # BRIDGE MODE: the branch's number lives on Vachanam's own WABA and sends
    # with the platform token. Non-NULL = the clinic owns its WABA and this is
    # their Fernet-encrypted business token. One resolver, two modes, so the
    # Tech Provider switch is a per-clinic flag flip and not a rewrite.
    wa_waba_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True
    )
    wa_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # none | connected | disconnected | error
    wa_status: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none", nullable=False
    )
    wa_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 4: Write the migration**

```python
# alembic/versions/mm36_branch_wa_credentials.py
"""branches — per-branch WhatsApp credentials (bridge mode → Tech Provider).

Additive. NULL wa_token_enc keeps every existing branch on the platform token
exactly as today, so this migration changes no behaviour on its own.

Revision ID: mm36_wa_credentials
Revises: ll35_question_answer
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mm36_wa_credentials"
down_revision: str | Sequence[str] | None = "ll35_question_answer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("wa_waba_id", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_branches_wa_waba_id", "branches", ["wa_waba_id"])
    op.add_column("branches", sa.Column("wa_token_enc", sa.Text(), nullable=True))
    op.add_column(
        "branches",
        sa.Column("wa_status", sa.String(16), nullable=False, server_default="none"),
    )
    op.add_column(
        "branches",
        sa.Column("wa_connected_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("branches", "wa_connected_at")
    op.drop_column("branches", "wa_status")
    op.drop_column("branches", "wa_token_enc")
    op.drop_constraint("uq_branches_wa_waba_id", "branches", type_="unique")
    op.drop_column("branches", "wa_waba_id")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_wa_branch_credentials.py -q`
Expected: PASS (2 tests). Then `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini')).get_heads())"` → `['mm36_wa_credentials']` (single head).

- [ ] **Step 6: Commit**

```bash
git add backend/models/schema.py alembic/versions/mm36_branch_wa_credentials.py tests/integration/test_wa_branch_credentials.py
git commit -m "feat(wa): per-branch WhatsApp credential columns (bridge mode seam)"
```

---

### Task 2: Per-branch token resolver in wa_service

**Files:**
- Modify: `backend/services/wa_service.py:29-84` (`wa_enabled`, `_post`, `_send`)
- Test: `tests/unit/test_wa_service.py` (append)

**Interfaces:**
- Consumes: `Branch.wa_token_enc` (Task 1), `backend.services.crypto.decrypt_secret`.
- Produces: `wa_service.token_for(branch) -> str` — the branch's decrypted token when set, else `settings.meta_access_token`, else `""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_wa_service.py`:

```python
def _branch_with_token(token_enc):
    return SimpleNamespace(
        id=uuid.uuid4(), wa_phone_number_id="999888777", wa_token_enc=token_enc
    )


def test_bridge_mode_uses_the_platform_token(monkeypatch):
    """wa_token_enc NULL → platform token (every branch today)."""
    monkeypatch.setattr(settings, "meta_access_token", "PLATFORM", raising=False)
    assert wa_service.token_for(_branch_with_token(None)) == "PLATFORM"


def test_branch_token_wins_over_the_platform_token(monkeypatch):
    """Tech Provider mode: the clinic's own token is used, never the platform one."""
    from backend.services.crypto import encrypt_secret

    monkeypatch.setattr(settings, "meta_access_token", "PLATFORM", raising=False)
    assert wa_service.token_for(_branch_with_token(encrypt_secret("CLINIC"))) == "CLINIC"


@pytest.mark.asyncio
async def test_send_authorizes_with_the_branch_token(monkeypatch):
    """RULE 1: the Authorization header carries THIS branch's credential."""
    from backend.services.crypto import encrypt_secret

    sent = []
    monkeypatch.setattr(settings, "meta_access_token", "PLATFORM", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _capture_post(sent))
    br = _branch_with_token(encrypt_secret("CLINIC"))
    ok = await wa_service.send_text(br, "+919876500011", "hi", plan="clinic")
    assert ok is True
    assert sent[0]["headers"]["Authorization"] == "Bearer CLINIC"
    assert "999888777/messages" in sent[0]["url"]


@pytest.mark.asyncio
async def test_no_token_anywhere_is_a_silent_noop(monkeypatch):
    """No platform token and no branch token → False, never a crash (RULE 4)."""
    monkeypatch.setattr(settings, "meta_access_token", "", raising=False)
    br = _branch_with_token(None)
    assert await wa_service.send_text(br, "+919876500011", "hi", plan="clinic") is False


@pytest.mark.asyncio
async def test_a_corrupt_branch_token_never_falls_back_to_the_platform(monkeypatch):
    """A tampered token must fail closed — sending on a clinic's number with
    the platform credential is exactly the cross-tenant mistake to avoid."""
    monkeypatch.setattr(settings, "meta_access_token", "PLATFORM", raising=False)
    br = _branch_with_token("not-a-fernet-token")
    assert await wa_service.send_text(br, "+919876500011", "hi", plan="clinic") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_wa_service.py -q`
Expected: FAIL — `AttributeError: module 'backend.services.wa_service' has no attribute 'token_for'`.

- [ ] **Step 3: Implement the resolver**

Replace `wa_service.py` lines 29-84 as follows. `wa_enabled` gains the token check; `_post` takes the token; `_send` resolves once.

```python
def token_for(branch) -> str:
    """The credential this branch sends with.

    NULL wa_token_enc = bridge mode: the number lives on Vachanam's own WABA
    and uses the platform token. A stored token means the clinic owns its WABA
    (Tech Provider). A stored token that will not decrypt returns "" — we fail
    closed rather than silently sending on a clinic's number with the platform
    credential (RULE 1).
    """
    enc = getattr(branch, "wa_token_enc", None)
    if enc:
        from backend.services.crypto import decrypt_secret

        try:
            return decrypt_secret(enc)
        except ValueError:
            logger.error(
                "wa_branch_token_undecryptable",
                branch_id=str(getattr(branch, "id", None)),
            )
            return ""
    return settings.meta_access_token or ""


def wa_enabled(branch, plan: str | None) -> bool:
    """True when this branch can send WhatsApp right now: a usable credential,
    a linked number, and an org plan that includes WhatsApp."""
    if not token_for(branch):
        logger.debug("wa_skipped_unconfigured", reason="no_token")
        return False
    if not getattr(branch, "wa_phone_number_id", None):
        logger.debug(
            "wa_skipped_unconfigured", reason="branch_not_linked",
            branch_id=str(getattr(branch, "id", None)),
        )
        return False
    if (plan or "") not in WHATSAPP_PLANS:
        logger.info(
            "wa_skipped_plan", plan=plan,
            branch_id=str(getattr(branch, "id", None)),
        )
        return False
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)
async def _post(phone_number_id: str, payload: dict, token: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{_GRAPH}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        r.raise_for_status()


async def _send(branch, plan: str | None, to: str, payload: dict, kind: str, detail: str) -> bool:
    """Shared guarded send. RULE 4: catches everything terminal."""
    if not wa_enabled(branch, plan):
        return False
    try:
        await _post(branch.wa_phone_number_id, payload, token_for(branch))
        logger.info(
            "wa_sent", kind=kind, detail=detail,
            to_last4=to[-4:] if to else None, branch_id=str(branch.id),
        )
        return True
    except Exception as e:  # noqa: BLE001 — notification channel, never raises out
        logger.warning(
            "wa_send_failed", kind=kind, detail=detail,
            to_last4=to[-4:] if to else None, branch_id=str(branch.id),
            error=str(e)[:200],
        )
        return False
```

Also update the module docstring's first paragraph to say the token is per-branch with a platform fallback.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_wa_service.py tests/integration/test_wa_confirmation.py tests/integration/test_wa_outbound_jobs.py -q`
Expected: PASS — new tests plus every existing wa test (they use `SimpleNamespace` branches without `wa_token_enc`, which `getattr(..., None)` handles).

- [ ] **Step 5: Commit**

```bash
git add backend/services/wa_service.py tests/unit/test_wa_service.py
git commit -m "feat(wa): per-branch token resolver with platform fallback"
```

---

### Task 3: WhatsApp-only prompt module

**Files:**
- Create: `agent/prompts/whatsapp_prompt.py`
- Modify: `backend/services/wa_chat.py:35-53` (delete the inline `_PROMPT`, import instead)
- Test: `tests/unit/test_whatsapp_prompt.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `agent.prompts.whatsapp_prompt.build_chat_prompt(faq: str, text: str) -> str` and the module constant `INTENTS: tuple[str, ...]`.

**Why a separate module:** the voice prompt in `agent/prompts/grounded_prompt.py` is built for speech — emotion tags (`[hesitates]`), fillers, "speak the date in words", TTS sanitization (RULE 6), interruption handling. Every one of those is wrong in text, where digits read better than words, formatting exists, and the patient may reply three hours later. The two prompts must never share a file or drift into each other.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_whatsapp_prompt.py
"""The WhatsApp prompt is text-native and must never inherit voice rules."""
from agent.prompts.whatsapp_prompt import INTENTS, build_chat_prompt

FAQ = "Q: What are the timings?\nA: 9am to 8pm, closed Sunday."


def test_prompt_carries_the_clinic_faq_and_the_patient_text():
    p = build_chat_prompt(FAQ, "what time do you open?")
    assert "9am to 8pm" in p
    assert "what time do you open?" in p


def test_prompt_has_no_voice_only_machinery():
    """Emotion tags, fillers and speech pacing belong to the phone agent."""
    p = build_chat_prompt(FAQ, "hi").lower()
    for voice_ism in ("[hesitates]", "filler", "pacing", "speak the date",
                      "tts", "pronounce", "interrupt"):
        assert voice_ism not in p, f"voice rule leaked into the chat prompt: {voice_ism}"


def test_prompt_mirrors_the_patient_language_and_stays_short():
    p = build_chat_prompt(FAQ, "repu appointment kaavali")
    assert "same language" in p.lower()
    assert "3 sentences" in p or "three sentences" in p.lower()


def test_no_medical_role():
    assert "never give medical advice" in build_chat_prompt(FAQ, "fever").lower()


def test_unknown_question_is_its_own_intent():
    """MVP1: an unanswerable CLINIC question goes to the doctor, not to
    'please call us' — Vinay 2026-08-02."""
    assert "ask_doctor" in INTENTS
    assert "ask_doctor" in build_chat_prompt(FAQ, "do you have a plastic surgeon?")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_whatsapp_prompt.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.prompts.whatsapp_prompt'`.

- [ ] **Step 3: Write the module**

```python
# agent/prompts/whatsapp_prompt.py
"""The WhatsApp assistant's prompt — deliberately NOT the voice prompt.

Text is a different medium: digits read better than words, formatting exists,
there is no interruption to recover from, and the patient may answer three
hours later. So none of the speech machinery (emotion tags, fillers, pacing,
TTS sanitization, spoken dates) belongs here, and nothing in this file may be
imported from `grounded_prompt`. Keeping them apart is the point.

MVP1 scope: classify ONE message. Booking over chat arrives with the
channel-agnostic booking brain (MVP4).
"""
from __future__ import annotations

INTENTS: tuple[str, ...] = (
    "reschedule", "cancel", "location", "faq", "ask_doctor", "booking", "other",
)

_TEMPLATE = (
    "You are an Indian clinic's WhatsApp assistant. You classify ONE message a "
    "patient sent, and nothing else. You have NO medical role: never give "
    "medical advice, diagnoses, or urgency judgments (hard rule).\n"
    "Clinic FAQ — the ONLY clinic knowledge you may answer from:\n{faq}\n\n"
    "Patient message: {text}\n\n"
    "Intents:\n"
    "- reschedule: wants to move an existing appointment\n"
    "- cancel: wants to cancel an existing appointment\n"
    "- location: asks where the clinic is / directions\n"
    "- faq: answerable strictly from the FAQ above\n"
    "- ask_doctor: a question ABOUT THE CLINIC that the FAQ does not answer "
    "(services offered, a specialist they want, fees not listed, facilities). "
    "The clinic will check with the doctor and reply later.\n"
    "- booking: wants a NEW appointment\n"
    "- other: anything else, including medical questions and complaints\n\n"
    "Writing rules for the answer field: plain text a person reads on a phone, "
    "maximum 3 sentences, no markdown headings, no bullet lists, at most one "
    "emoji and only if the patient used one, and the SAME language as the "
    "patient's message (Telugu script in, Telugu script out; romanised in, "
    "romanised out).\n"
    'Reply as JSON: {{"intent": string, "answer": string}} — answer is filled '
    "ONLY for intent=faq; empty string otherwise."
)


def build_chat_prompt(faq: str, text: str) -> str:
    """Prompt for one inbound WhatsApp message. `text` is truncated by the
    caller; it is never logged or stored (D14)."""
    return _TEMPLATE.format(faq=faq, text=text)
```

- [ ] **Step 4: Point wa_chat at it**

In `backend/services/wa_chat.py`: delete the `_PROMPT = (...)` block (lines 35-53) and replace the prompt construction inside `handle_text`:

```python
from agent.prompts.whatsapp_prompt import build_chat_prompt
```

```python
        prompt = build_chat_prompt(_faq_text(branch), text[:500])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_whatsapp_prompt.py tests/integration/test_wa_webhook.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/prompts/whatsapp_prompt.py backend/services/wa_chat.py tests/unit/test_whatsapp_prompt.py
git commit -m "feat(wa): text-native WhatsApp prompt module, split from the voice prompt"
```

---

### Task 4: Unknown clinic questions go to the doctor, not to "call us"

**Files:**
- Modify: `backend/services/wa_chat.py` (`handle_text` intent branches)
- Test: `tests/integration/test_wa_ask_doctor.py`

**Interfaces:**
- Consumes: `whatsapp_prompt.INTENTS` (Task 3), `backend.models.schema.ClinicQuestion` (shipped 2026-08-02).
- Produces: nothing new — reuses the existing question → doctor → callback loop.

**Behaviour:** intent `ask_doctor` writes a `ClinicQuestion` for this branch with the patient's phone, then replies "I'll check with the doctor and get back to you." The doctor answers it on the dashboard exactly as they do for phone questions; the existing callback job phones the patient. (Delivering that answer over WhatsApp instead is MVP2.) Intent `booking` keeps the call-the-clinic line — MVP1 cannot book (§0.5).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_wa_ask_doctor.py
"""MVP1: a clinic question the FAQ cannot answer reaches the doctor.

Vinay 2026-08-02: "when any unknown question asked, reply I'll confirm with
doctor and get back" — not "please call us"."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from backend.models.schema import Branch, ClinicQuestion, Organization
from backend.services import wa_chat


async def _branch(db):
    org = Organization(
        id=uuid.uuid4(), name="Ask Org", owner_phone="+919000022222",
        owner_email=f"ask-{uuid.uuid4()}@c.test", plan="clinic",
    )
    db.add(org)
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="Ask Clinic",
                whatsapp_number="+910000000201", wa_phone_number_id="7778889990")
    db.add(br)
    await db.commit()
    return br


@pytest.fixture(autouse=True)
def _platform_token(monkeypatch):
    """handle_text no-ops without a usable credential (wa_enabled) — give the
    suite a platform token so the intent branches actually run."""
    from backend.config import settings

    monkeypatch.setattr(settings, "meta_access_token", "TEST-TOKEN", raising=False)


@pytest.mark.asyncio
async def test_ask_doctor_logs_a_question_and_promises_a_reply(db):
    br = await _branch(db)
    sent = []
    with patch.object(wa_chat, "_call_gemini",
                      new=AsyncMock(return_value='{"intent": "ask_doctor", "answer": ""}')), \
         patch.object(wa_chat.wa_service, "send_text",
                      new=AsyncMock(side_effect=lambda b, to, text, plan=None: sent.append(text) or True)):
        await wa_chat.handle_text(db, br, "clinic", "+919876547554",
                                  "do you have a plastic surgeon?")

    rows = (await db.execute(
        select(ClinicQuestion).where(ClinicQuestion.branch_id == br.id)
    )).scalars().all()
    assert len(rows) == 1
    assert "plastic surgeon" in rows[0].question
    assert rows[0].caller_phone == "+919876547554"   # the callback address
    assert sent and "doctor" in sent[0].lower()
    assert "call" not in sent[0].lower()             # never the call-us line


@pytest.mark.asyncio
async def test_a_new_booking_still_points_at_the_phone_line(db):
    """MVP1 cannot book over chat — that is MVP4. It must not pretend to."""
    br = await _branch(db)
    sent = []
    with patch.object(wa_chat, "_call_gemini",
                      new=AsyncMock(return_value='{"intent": "booking", "answer": ""}')), \
         patch.object(wa_chat.wa_service, "send_text",
                      new=AsyncMock(side_effect=lambda b, to, text, plan=None: sent.append(text) or True)):
        await wa_chat.handle_text(db, br, "clinic", "+919876547554", "book me tomorrow")
    assert sent
    assert (await db.execute(select(ClinicQuestion))).scalars().first() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_wa_ask_doctor.py -q`
Expected: FAIL — no `ClinicQuestion` row (the `ask_doctor` branch does not exist yet).

- [ ] **Step 3: Implement the branch**

In `wa_chat.handle_text`, before the final `else`:

```python
    elif intent == "ask_doctor":
        # The FAQ could not answer a CLINIC question. Log it for the doctor
        # (same table the phone agent writes) and promise a reply — never the
        # call-us line, which is what clinics are paying us to remove.
        from backend.models.schema import ClinicQuestion, Patient

        q = " ".join((text or "").split())[:300]
        pid = (await db.execute(
            select(Patient.id).where(
                Patient.branch_id == branch.id, Patient.phone == sender
            ).limit(1)
        )).scalar_one_or_none()
        db.add(ClinicQuestion(
            branch_id=branch.id, question=q,
            caller_last4=(sender or "")[-4:] or None,
            patient_id=pid, caller_phone=sender or None,
        ))
        await db.commit()
        logger.info("wa_question_logged", branch_id=str(branch.id),
                    to_last4=(sender or "")[-4:])
        await wa_service.send_text(
            branch, sender,
            "Let me check that with the doctor and get back to you shortly.",
            plan=plan,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_wa_ask_doctor.py tests/integration/test_wa_webhook.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/wa_chat.py tests/integration/test_wa_ask_doctor.py
git commit -m "feat(wa): unknown clinic questions reach the doctor instead of a call-us line"
```

---

### Task 5: Templates send in English only (D5)

**Files:**
- Modify: `backend/services/wa_templates.py:24-30`
- Test: `tests/unit/test_wa_templates_lang.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `template_lang(preferred: str | None) -> str` — always `"en"`. Signature unchanged so no caller moves.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_wa_templates_lang.py
"""D5: WhatsApp templates are English only, whatever the clinic's voice language."""
from backend.services.wa_templates import template_lang


def test_every_clinic_language_sends_the_english_template():
    for preferred in ("te", "hi", "ta", "kn", "mr", "en", "", None):
        assert template_lang(preferred) == "en"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_wa_templates_lang.py -q`
Expected: FAIL — `assert 'te' == 'en'`.

- [ ] **Step 3: Implement**

```python
def template_lang(preferred: str | None) -> str:
    """Templates are English only (D5, Vinay 2026-08-02): the clinic writes and
    approves one English copy per template. `preferred` is kept in the signature
    so callers do not move when per-language templates return."""
    return "en"
```

Delete the now-unused `_DAY1_LANGS` constant.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_wa_templates_lang.py tests/integration/test_wa_confirmation.py tests/integration/test_wa_outbound_jobs.py -q`
Expected: PASS. If an existing test asserts a `te` template language, update that assertion to `en` in the same commit — D5 is the newer decision.

- [ ] **Step 5: Commit**

```bash
git add backend/services/wa_templates.py tests/unit/test_wa_templates_lang.py
git commit -m "feat(wa): templates send in English only (D5)"
```

---

### Task 6: Connection status visible to the clinic owner

**Files:**
- Modify: `backend/routers/branches.py:97` (`BranchSettings`) and `:142` (`_settings_payload`)
- Modify: `frontend/src/pages/Settings.jsx` (WhatsApp status row)
- Test: `tests/integration/test_wa_settings_status.py`

**Interfaces:**
- Consumes: `Branch.wa_status`, `Branch.wa_phone_number_id`.
- Produces: `BranchSettings.whatsapp_status: str` — `"connected"` when a number is linked, else `"none"`.

**Note:** linking stays concierge — `PATCH /admin/branches/{id}/whatsapp` (super_admin) already exists and is tested. MVP1 adds visibility only; self-serve connect is MVP6.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_wa_settings_status.py
"""MVP1: the owner can see whether WhatsApp is live for their clinic."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import Branch, Organization


def _owner(branch_id, org_id):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@c.com", role="org_admin",
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


async def _seed(db, wa_number_id):
    org = Organization(
        id=uuid.uuid4(), name="St Org", owner_phone="+919000033333",
        owner_email=f"st-{uuid.uuid4()}@c.test", plan="clinic",
    )
    db.add(org)
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="St Clinic",
                whatsapp_number=f"+9100000003{wa_number_id[-2:]}",
                wa_phone_number_id=wa_number_id or None)
    db.add(br)
    await db.commit()
    return org, br


@pytest.mark.asyncio
async def test_linked_branch_reports_connected(db):
    org, br = await _seed(db, "5551234567")
    app.dependency_overrides[get_current_user] = lambda: _owner(br.id, org.id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get(f"/branches/{br.id}/settings")
            assert r.status_code == 200, r.text
            assert r.json()["whatsapp_status"] == "connected"
            assert r.json()["whatsapp_linked"] is True
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_wa_settings_status.py -q`
Expected: FAIL — `KeyError: 'whatsapp_status'`.

- [ ] **Step 3: Implement**

`backend/routers/branches.py` — in `BranchSettings`, below `whatsapp_linked`:

```python
    whatsapp_status: str = "none"  # none | connected — linking stays concierge
```

In `_settings_payload`, alongside the existing `whatsapp_linked=`:

```python
        whatsapp_status=(
            "connected" if getattr(branch, "wa_phone_number_id", None) else "none"
        ),
```

`frontend/src/pages/Settings.jsx` — in the section that already renders clinic
details, add a read-only row (place it directly after the FAQ section):

```jsx
<Section id="whatsapp" title="WhatsApp">
  <p className="font-ui text-sm text-slate">
    {data?.whatsapp_status === "connected"
      ? "WhatsApp is live for this clinic — confirmations, reminders and patient questions are handled automatically."
      : "WhatsApp is not connected yet. We set this up for you — contact support to start."}
  </p>
  <span className={`chip mt-2 ${data?.whatsapp_status === "connected" ? "bg-gold-soft text-gold-ink" : "chip-muted"}`}>
    {data?.whatsapp_status === "connected" ? "Connected" : "Not connected"}
  </span>
</Section>
```

Match the surrounding `Section` usage in that file; if the settings query variable is not named `data`, use the local name already in scope.

- [ ] **Step 4: Run tests and the build**

Run: `python -m pytest tests/integration/test_wa_settings_status.py tests/integration/test_settings_end_to_end.py -q`
Expected: PASS.
Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/branches.py frontend/src/pages/Settings.jsx tests/integration/test_wa_settings_status.py
git commit -m "feat(wa): show WhatsApp connection status on clinic settings"
```

---

### Task 7: Go-live runbook, smoke script, docs

**Files:**
- Create: `docs/runbooks/whatsapp-mvp1.md`
- Create: `scripts/wa_smoke.py`
- Modify: `docs/CHANGELOG.md`, `docs/STATUS.md`, `.env.example`

**Interfaces:**
- Consumes: `wa_service.send_template`, `Branch`.
- Produces: `python scripts/wa_smoke.py --phone-number-id <id> --to +91XXXXXXXXXX` — sends `booking_confirm` and prints the Graph result.

- [ ] **Step 1: Write the smoke script**

```python
# scripts/wa_smoke.py
"""Send one real WhatsApp template through the live path (MVP1 verification).

Usage:
    python scripts/wa_smoke.py --phone-number-id 5551234567 --to +919876543210

Uses the same wa_service the product uses, so a success here proves the token,
the number link, the template approval and the plan gate all line up.
"""
from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

from backend.services import wa_service


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone-number-id", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--template", default="booking_confirm")
    args = ap.parse_args()

    branch = SimpleNamespace(
        id="smoke", wa_phone_number_id=args.phone_number_id, wa_token_enc=None
    )
    ok = await wa_service.send_template(
        branch, args.to, args.template, "en",
        ["Test Patient", "Dr Srinivas", "tomorrow 10:30", "12"],
        plan="clinic",
    )
    print("sent" if ok else "FAILED — check the logs above")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write the runbook**

Create `docs/runbooks/whatsapp-mvp1.md` with these sections, in order, each a checkbox: (1) App Settings → Basic: icon, category, privacy policy `https://vachanam.in/privacy`; (2) App Mode → **Live**; (3) WhatsApp Manager → Payment configuration → add an India payment method; (4) add the pilot number to the WABA with the WhatsApp **Business app** installed (coexistence) and complete OTP; (5) submit `booking_confirm`, `appt_reminder`, `rating_ask`, `leave_rebook` for approval, English; (6) Render env: `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`; (7) App Dashboard → WhatsApp → Configuration: callback `https://vachanam-backend.onrender.com/webhooks/whatsapp`, the same verify token, subscribe `messages` and `message_template_status_update`; (8) `PATCH /admin/branches/{id}/whatsapp` with the `phone_number_id`; (9) run `scripts/wa_smoke.py`; (10) message the number from a patient phone and confirm an FAQ answer arrives. Record the 250 business-initiated conversations/24h ceiling and that it is shared across every number on the WABA until verification clears.

- [ ] **Step 3: Sync `.env.example`**

Confirm `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`, `META_PHONE_NUMBER_ID`, `META_WABA_ID` all appear with empty defaults and names matching `backend/config.py` exactly. Add any that are missing.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q --ignore=tests/e2e`
Expected: PASS — 1,517 + the new tests, 0 failures.
Run: `python -m ruff check backend agent scripts tests`
Expected: clean.

- [ ] **Step 5: Write the docs rows and commit**

Add a CHANGELOG entry and a STATUS block describing MVP1: what ships, that chat booking is NOT included, and that migration `mm36_wa_credentials` is deploy-gated until applied.

```bash
git add docs/runbooks/whatsapp-mvp1.md scripts/wa_smoke.py docs/CHANGELOG.md docs/STATUS.md .env.example
git commit -m "docs(wa): MVP1 go-live runbook, smoke script, status"
```

---

## Deployment

1. Merge to `master` → CI green → tag + Fly deploy (agent) and Render (API) auto-deploy.
2. **Apply `mm36_wa_credentials` to production before the API deploy lands** — the pattern from 2026-08-02: the migration first, then the code that reads the columns. `wa_status` has a server default, so an older API against the newer schema is also safe.
3. Work the runbook top to bottom, then send a real message.

## Out of scope (do not build here)

The WhatsApp page and its tabs (MVP2/MVP3), `wa_events`, `smb_message_echoes`
handling, custom templates, broadcasts, conversational booking (MVP4), the
patient-page timeline and the three fallbacks (MVP5), self-serve Embedded Signup
(MVP6), the doctor command channel (MVP7).
