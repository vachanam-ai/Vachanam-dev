# Support System — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the self-serve support core — a Gemini-grounded FAQ chatbot that auto-logs every chat as a ticket (answered → `ai_resolved`, stuck → `open`), a searchable Help page (public + in-app), and a clinic-facing "My Tickets" log/thread view — backed by two new org-scoped tables.

**Architecture:** A markdown knowledge base in `docs/support/*.md` is loaded in-memory and filtered by audience. `POST /support/chat` (auth-optional) grounds Gemini 2.5-flash-lite on that KB, refuses when the answer isn't present, and writes one `support_ticket` + threaded `support_messages` per chat session. Ticket reads are strictly `WHERE org_id` scoped. Everything reuses existing infra (Gemini call_scoring pattern, `require_turnstile`, `default_limit`, Resend) — no new vendors, no new secrets.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, `google-genai` (async client), pyrate-limiter, React 18 + Vite + TanStack Query + Tailwind (CSS-var tokens).

## Global Constraints

- Branch: `master`. Migrations are **deploy-gated** — author the Alembic migration but DO NOT apply to prod (Vinay confirms separately). Tests get the tables via conftest's `Base.metadata.create_all`.
- RULE 1 (tenant isolation): the chatbot has NO clinic-data access and NO DB read of patient/token rows; ticket reads are `WHERE org_id = current_user.org_id`; a clinic must get 404 on another clinic's ticket.
- RULE 8 (graceful external): Gemini failure → fallback / safe refusal, never a 500 on the chat path; any email is best-effort and never blocks a write (no email in Phase 1).
- RULE 9 (PII discipline): structlog logs ticket/message **IDs**, never bodies; last-4 only if a phone is ever logged.
- Internal role keys stay `super_admin|org_admin|receptionist|doctor`; Phase 1 adds the value `"support"` to the `user_role` enum list only (no route uses it yet — that's Phase 2).
- Ticket `status` enum values (exact): `ai_resolved`, `open`, `pending`, `resolved`, `closed`.
- Ticket `category` enum values (exact): `billing`, `technical`, `onboarding`, `feature_request`, `sales_demo`, `other`.
- Ticket `source` enum values (exact): `in_app`, `public_chat`, `public_form`, `email`.
- Message `sender` enum values (exact): `user`, `staff`, `bot`, `system`.
- Bounded inputs (mirror FIXLOG #313): chat `question` ≤ 2000 chars, `history` ≤ 20 turns, ticket `subject` ≤ 200, `body` ≤ 8000 — enforced with Pydantic `Field(..., max_length=…)` / list length checks → 422.
- Run the full suite green after each backend task (`python -m pytest tests/ -q`, Docker Postgres+Redis up). Frontend tasks gate on `npm run build`.
- Every task: FIXLOG.md is updated once at the end (Task 12), not per-task; but each task commits with a conventional message.

---

## File Structure

- `backend/models/schema.py` — **modify**: add `SupportTicket`, `SupportMessage` models; add `"support"` to the `user_role` Enum value list.
- `alembic/versions/<rev>_support_tables.py` — **create**: additive migration (two CREATE TABLEs), deploy-gated.
- `backend/services/support_kb.py` — **create**: load + front-matter-parse `docs/support/*.md`, audience filter, in-memory cache. One responsibility: KB access.
- `docs/support/*.md` — **create**: the KB corpus (Task 3 seeds a starter set).
- `backend/services/support_bot.py` — **create**: Gemini-grounded answer + `answered` flag + fallback. One responsibility: the LLM call.
- `backend/middleware/auth_middleware.py` — **modify**: add `optional_current_user(request)` returning `CurrentUser | None` (the public+authed chat route needs auth WITHOUT `HTTPBearer(auto_error=True)`).
- `backend/routers/support.py` — **create**: `/support/kb`, `/support/chat`, `/support/tickets*` routes.
- `backend/main.py` — **modify**: mount the support router.
- `frontend/src/api/support.js` — **create**: axios calls.
- `frontend/src/pages/Help.jsx` — **create**: KB search + chat widget (public + in-app).
- `frontend/src/pages/MyTickets.jsx` — **create**: ticket log + thread view (in-app).
- `frontend/src/App.jsx` + Shell nav — **modify**: routes + nav entry.

---

### Task 1: Support tables (models)

**Files:**
- Modify: `backend/models/schema.py`
- Test: `tests/unit/test_support_models.py`

**Interfaces:**
- Produces: `SupportTicket` (cols: `id`, `org_id` nullable FK, `email`, `name`, `subject`, `category`, `status`, `priority`, `sla_due_at`, `first_responded_at`, `resolved_at`, `csat_score`, `csat_comment`, `source`, `created_at`, `updated_at`), `SupportMessage` (cols: `id`, `ticket_id` FK, `sender`, `sender_user_id`, `body`, `created_at`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_support_models.py
import uuid
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


async def test_ticket_and_message_roundtrip(db):
    from backend.models.schema import Organization, SupportTicket, SupportMessage

    org = Organization(
        name="C", owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
        plan="clinic", status="trial",
    )
    db.add(org)
    await db.flush()

    t = SupportTicket(
        org_id=org.id, email="o@t.com", subject="help",
        category="technical", status="open", priority="normal", source="in_app",
    )
    db.add(t)
    await db.flush()
    db.add(SupportMessage(ticket_id=t.id, sender="user", body="my call failed"))
    await db.commit()
    await db.refresh(t)
    assert t.status == "open"
    assert t.org_id == org.id


async def test_public_ticket_allows_null_org(db):
    from backend.models.schema import SupportTicket

    t = SupportTicket(
        org_id=None, email="lead@x.com", name="Lead", subject="demo",
        category="sales_demo", status="open", priority="normal", source="public_form",
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    assert t.org_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_support_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'SupportTicket'`.

- [ ] **Step 3: Add the models to `backend/models/schema.py`**

Append at the end of the file (after the last model). `Base`, `Mapped`, `mapped_column`, `UUID`, `String`, `Text`, `Integer`, `DateTime`, `Date`, `Enum`, `ForeignKey`, `func`, `Index` are already imported at the top.

```python
class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL org_id = a public lead (contact/demo form, no auth). Non-null = a clinic
    # ticket. This is the ONLY scope — support is org-level, never branch data.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(
        Enum("billing", "technical", "onboarding", "feature_request", "sales_demo",
             "other", name="support_category"),
        nullable=False, default="other",
    )
    status: Mapped[str] = mapped_column(
        Enum("ai_resolved", "open", "pending", "resolved", "closed",
             name="support_status"),
        nullable=False, default="open",
    )
    priority: Mapped[str] = mapped_column(
        Enum("low", "normal", "high", "urgent", name="support_priority"),
        nullable=False, default="normal",
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csat_score: Mapped[int | None] = mapped_column(Integer)
    csat_comment: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        Enum("in_app", "public_chat", "public_form", "email", name="support_source"),
        nullable=False, default="in_app",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("ix_support_tickets_status_sla", "status", "sla_due_at"),)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender: Mapped[str] = mapped_column(
        Enum("user", "staff", "bot", "system", name="support_sender"), nullable=False
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_support_messages_ticket_created", "ticket_id", "created_at"),)
```

Also add `"support"` to the `user_role` Enum value list (the line near the bottom of the User model):

```python
# BEFORE
Enum("super_admin", "org_admin", "receptionist", "doctor", name="user_role", create_constraint=False),
# AFTER
Enum("super_admin", "org_admin", "receptionist", "doctor", "support", name="user_role", create_constraint=False),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_support_models.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/models/schema.py tests/unit/test_support_models.py
git commit -m "feat(support): support_tickets + support_messages models + support role value"
```

---

### Task 2: Deploy-gated Alembic migration

**Files:**
- Create: `alembic/versions/<rev>_support_tables.py`
- Test: `tests/unit/test_migration_support_head.py`

**Interfaces:**
- Consumes: the models from Task 1.
- Produces: a migration whose `revision` is the new head; `down_revision` = the prior head.

> The base Alembic chain is broken (memory `alembic-chain-broken`); prod is upgraded by applying the head migration, tests use `create_all`. This migration must be additive and standalone.

- [ ] **Step 1: Find the current head**

Run: `python -m alembic heads`
Expected: prints one revision id, e.g. `z23xxxx (head)`. Record it as `<PRIOR_HEAD>`.

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_migration_support_head.py
def test_support_migration_defines_both_tables():
    import importlib, pathlib, re
    versions = pathlib.Path("alembic/versions")
    src = next(p for p in versions.glob("*_support_tables.py")).read_text()
    assert "create_table" in src and "support_tickets" in src and "support_messages" in src
    # down_revision must be set (chained to a real prior head, not None)
    assert re.search(r"down_revision\s*=\s*['\"]\w+['\"]", src)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_migration_support_head.py -q`
Expected: FAIL — `StopIteration` (no `*_support_tables.py` yet).

- [ ] **Step 4: Create the migration**

`alembic/versions/aa24_support_tables.py` (replace `<PRIOR_HEAD>` with the id from Step 1):

```python
"""support tickets + messages (additive, deploy-gated)

Revision ID: aa24_support_tables
Revises: <PRIOR_HEAD>
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "aa24_support_tables"
down_revision = "<PRIOR_HEAD>"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "support_tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("category", sa.Enum("billing", "technical", "onboarding", "feature_request", "sales_demo", "other", name="support_category"), nullable=False),
        sa.Column("status", sa.Enum("ai_resolved", "open", "pending", "resolved", "closed", name="support_status"), nullable=False),
        sa.Column("priority", sa.Enum("low", "normal", "high", "urgent", name="support_priority"), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True)),
        sa.Column("first_responded_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("csat_score", sa.Integer),
        sa.Column("csat_comment", sa.Text),
        sa.Column("source", sa.Enum("in_app", "public_chat", "public_form", "email", name="support_source"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_tickets_org_id", "support_tickets", ["org_id"])
    op.create_index("ix_support_tickets_status_sla", "support_tickets", ["status", "sla_due_at"])
    op.create_table(
        "support_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", UUID(as_uuid=True), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender", sa.Enum("user", "staff", "bot", "system", name="support_sender"), nullable=False),
        sa.Column("sender_user_id", UUID(as_uuid=True)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_messages_ticket_created", "support_messages", ["ticket_id", "created_at"])


def downgrade():
    op.drop_table("support_messages")
    op.drop_table("support_tickets")
    for e in ("support_sender", "support_source", "support_priority", "support_status", "support_category"):
        op.execute(f"DROP TYPE IF EXISTS {e}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_migration_support_head.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/aa24_support_tables.py tests/unit/test_migration_support_head.py
git commit -m "feat(support): additive migration for support tables (deploy-gated)"
```

---

### Task 3: Knowledge-base service + seed corpus

**Files:**
- Create: `backend/services/support_kb.py`
- Create: `docs/support/what-is-vachanam.md`, `docs/support/languages.md`, `docs/support/pricing.md`, `docs/support/add-doctor.md`, `docs/support/connect-did.md`, `docs/support/call-failed.md`, `docs/support/billing-trial.md`, `docs/support/data-privacy.md` (starter set; more added later)
- Test: `tests/unit/test_support_kb.py`

**Interfaces:**
- Produces: `load_kb() -> list[dict]` (each `{title, audience, category, tags, body}`), `kb_text(audience: str) -> str` where `audience in ("public","clinic")` returns the concatenated markdown of entries whose front-matter `audience` is that value OR `both`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_support_kb.py
def test_kb_audience_filtering():
    from backend.services import support_kb

    pub = support_kb.kb_text("public")
    clin = support_kb.kb_text("clinic")
    assert pub and clin
    # a clinic-only entry (front-matter audience: clinic) must NOT leak to public
    assert "Connecting your phone number" not in pub  # connect-did.md is audience: clinic
    assert "Connecting your phone number" in clin


def test_kb_entries_have_frontmatter():
    from backend.services import support_kb

    for e in support_kb.load_kb():
        assert e["title"] and e["audience"] in ("public", "clinic", "both")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_support_kb.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.services.support_kb`.

- [ ] **Step 3: Write the KB service**

`backend/services/support_kb.py`:

```python
"""In-memory support knowledge base. KB = markdown files in docs/support/*.md
with a small YAML-ish front-matter block:

    ---
    title: Pricing & plans
    audience: public   # public | clinic | both
    category: billing
    tags: price, plan, cost
    ---
    <markdown body>

ponytail: loaded once at import into a module list; the corpus is tiny. Move to
a table + cache-bust only if it needs runtime edits or outgrows memory.
"""
from __future__ import annotations

import pathlib

_DIR = pathlib.Path(__file__).resolve().parents[2] / "docs" / "support"


def _parse(text: str) -> dict:
    front, _, body = text.partition("---\n")[2].partition("\n---\n")
    meta = {}
    for line in front.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return {
        "title": meta.get("title", ""),
        "audience": meta.get("audience", "both"),
        "category": meta.get("category", "other"),
        "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        "body": body.strip(),
    }


def load_kb() -> list[dict]:
    if not _DIR.exists():
        return []
    return [_parse(p.read_text(encoding="utf-8")) for p in sorted(_DIR.glob("*.md"))]


_CACHE = load_kb()


def kb_text(audience: str) -> str:
    """Concatenated markdown for one audience. `both` entries always included."""
    parts = [
        f"## {e['title']}\n{e['body']}"
        for e in _CACHE
        if e["audience"] in (audience, "both")
    ]
    return "\n\n".join(parts)
```

- [ ] **Step 4: Seed the corpus**

Create the 8 files. Each starts with the front-matter block. Example `docs/support/connect-did.md` (this one MUST be `audience: clinic` so the test passes):

```markdown
---
title: Connecting your phone number
audience: clinic
category: onboarding
tags: did, number, phone, vobiz
---
Connecting your phone number to Vachanam takes a few minutes. After you buy a
number, add it in Settings → Telephony, then forward your clinic line to it.
Vachanam answers every call in your chosen language and books appointments.
```

`docs/support/what-is-vachanam.md` (`audience: both`), `languages.md` (`both`), `pricing.md` (`public`, category billing — Starter ₹5,999 / Clinic ₹9,999 / Multi ₹17,999, +18% GST, +₹5/min overage, 14-day free trial), `add-doctor.md` (`clinic`), `call-failed.md` (`both`), `billing-trial.md` (`both`), `data-privacy.md` (`both`, DPDP one-paragraph + link to /privacy). Keep each 3–6 sentences, plain language, no medical claims. Pricing values MUST match `backend/services/billing_math.py` verbatim.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_support_kb.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/services/support_kb.py docs/support/ tests/unit/test_support_kb.py
git commit -m "feat(support): markdown KB service + seed corpus (audience-filtered)"
```

---

### Task 4: Grounded chatbot service

**Files:**
- Create: `backend/services/support_bot.py`
- Test: `tests/unit/test_support_bot.py`

**Interfaces:**
- Consumes: `support_kb.kb_text`.
- Produces: `async def answer(question: str, history: list[dict], audience: str, plan: str | None = None) -> dict` returning `{"answer": str, "answered": bool}`. `answered=False` on refusal/LLM-failure (drives ticket status `open`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_support_bot.py
import pytest

pytestmark = pytest.mark.asyncio


async def test_bot_grounds_and_flags_answered(monkeypatch):
    from backend.services import support_bot

    async def fake_llm(prompt, **_):
        # assert the KB is actually in the grounding prompt
        assert "Pricing" in prompt or "plan" in prompt.lower()
        return '{"answer": "Starter is 5,999 rupees a month.", "answered": true}'

    monkeypatch.setattr(support_bot, "_call_gemini", fake_llm)
    out = await support_bot.answer("what does starter cost?", [], "public")
    assert out["answered"] is True
    assert "5,999" in out["answer"]


async def test_bot_llm_failure_is_safe_refusal(monkeypatch):
    from backend.services import support_bot

    async def boom(prompt, **_):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(support_bot, "_call_gemini", boom)
    out = await support_bot.answer("anything", [], "public")
    # RULE 8: never raise; refusal → answered False (becomes an open ticket)
    assert out["answered"] is False
    assert "hello@vachanam.in" in out["answer"] or "team" in out["answer"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_support_bot.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.services.support_bot`.

- [ ] **Step 3: Write the bot service**

`backend/services/support_bot.py`:

```python
"""Support chatbot — Gemini 2.5-flash-lite grounded on the support KB.

RULE 1: product questions only. NO tool access, NO clinic-data read. The
in-app variant may know the caller's plan (from the JWT) to answer "what's in
my plan", but never anything patient-level.
RULE 8: any LLM failure returns a safe refusal (answered=False), never raises.
No judge/sim rewrite loop (memory feedback-no-auto-prompt-tuning) — fixed prompt.
"""
from __future__ import annotations

import json

import structlog

from backend.config import settings
from backend.services import support_kb

logger = structlog.get_logger()

_FALLBACK = (
    "I'm not fully sure about that one — I've logged it so our team can help. "
    "You can also email hello@vachanam.in and we'll get back to you."
)

_SYSTEM = (
    "You are Vachanam's support assistant for Indian clinics. Answer ONLY from "
    "the KNOWLEDGE BASE below. If the answer is not in it, say you are not sure "
    "and that the team will follow up — do NOT invent pricing, features, or any "
    "medical advice. Keep it to 1-3 short sentences, plain text, no markdown "
    "symbols. Reply as JSON: {\"answer\": string, \"answered\": boolean} where "
    "answered is false when the knowledge base does not cover the question.\n\n"
    "KNOWLEDGE BASE:\n{kb}\n"
)


async def _call_gemini(prompt: str) -> str:
    """Isolated so tests swap it out. Async client (same loop as FastAPI)."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.gemini_api_key)
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
            temperature=0,
            max_output_tokens=400,
        ),
    )
    return resp.text or "{}"


async def answer(question: str, history: list[dict], audience: str,
                 plan: str | None = None) -> dict:
    kb = support_kb.kb_text(audience if audience in ("public", "clinic") else "public")
    plan_line = f"\nThe user's current plan is: {plan}." if plan else ""
    convo = "".join(
        f"\n{h.get('role', 'user')}: {h.get('content', '')}" for h in history[-20:]
    )
    prompt = _SYSTEM.format(kb=kb) + plan_line + convo + f"\nuser: {question}\n"
    try:
        raw = await _call_gemini(prompt)
        data = json.loads(raw)
        ans = (data.get("answer") or "").strip()
        answered = bool(data.get("answered")) and bool(ans)
        if not ans:
            return {"answer": _FALLBACK, "answered": False}
        return {"answer": ans, "answered": answered}
    except Exception as exc:  # noqa: BLE001 — RULE 8: never break the chat
        logger.warning("support_bot_failed", error=str(exc))
        return {"answer": _FALLBACK, "answered": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_support_bot.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/services/support_bot.py tests/unit/test_support_bot.py
git commit -m "feat(support): Gemini-grounded chatbot service (RULE 1/8)"
```

---

### Task 5: Optional-auth helper

**Files:**
- Modify: `backend/middleware/auth_middleware.py`
- Test: `tests/unit/test_optional_auth.py`

**Interfaces:**
- Consumes: the JWT decode logic already in `get_current_user`.
- Produces: `async def optional_current_user(request: Request) -> CurrentUser | None` — returns a `CurrentUser` for a valid Bearer token, `None` for missing/garbage/expired (NEVER raises 401). Used by `/support/chat`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_optional_auth.py
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from backend.config import settings

pytestmark = pytest.mark.asyncio


class _Req:
    def __init__(self, auth=None):
        self.headers = {"Authorization": auth} if auth else {}


def _tok(**over):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()), "email": "u@t.com", "role": "org_admin",
        "org_id": str(uuid.uuid4()), "branch_ids": [], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }
    payload.update(over)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def test_optional_auth_returns_user_for_valid_token():
    from backend.middleware.auth_middleware import optional_current_user
    u = await optional_current_user(_Req(f"Bearer {_tok()}"))
    assert u is not None and u.role == "org_admin"


async def test_optional_auth_returns_none_for_missing_or_garbage():
    from backend.middleware.auth_middleware import optional_current_user
    assert await optional_current_user(_Req(None)) is None
    assert await optional_current_user(_Req("Bearer garbage")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_optional_auth.py -q`
Expected: FAIL — `ImportError: cannot import name 'optional_current_user'`.

- [ ] **Step 3: Implement the helper**

Open `backend/middleware/auth_middleware.py`. Note the exact fields the `CurrentUser` dataclass is built with inside `get_current_user` (e.g. `user_id`, `email`, `role`, `org_id`, `branch_ids`, `is_admin`, `jti`) and reuse the SAME construction. Add:

```python
from fastapi import Request  # if not already imported

async def optional_current_user(request: Request) -> "CurrentUser | None":
    """Auth for public+authed routes: valid Bearer → CurrentUser, else None.
    Never raises (unlike get_current_user via HTTPBearer(auto_error=True))."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001 — any decode failure = anonymous
        return None
    # Build CurrentUser IDENTICALLY to get_current_user (copy that construction).
    return CurrentUser(
        user_id=payload.get("sub"),
        email=payload.get("email"),
        role=payload.get("role"),
        org_id=payload.get("org_id"),
        branch_ids=payload.get("branch_ids") or [],
        is_admin=bool(payload.get("is_admin")),
        jti=payload.get("jti"),
    )
```

> If `CurrentUser`'s constructor differs, match it exactly — read the `get_current_user` body first. Do NOT check the Redis revocation set here (anonymous-friendly path; a revoked token simply resolves to a still-valid-looking user for a non-privileged support chat — acceptable, no clinic data is exposed).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_optional_auth.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/middleware/auth_middleware.py tests/unit/test_optional_auth.py
git commit -m "feat(support): optional_current_user helper for public+authed routes"
```

---

### Task 6: Support router — KB + chat (auto-logs ticket)

**Files:**
- Create: `backend/routers/support.py`
- Modify: `backend/main.py` (mount)
- Test: `tests/integration/test_support_chat.py`

**Interfaces:**
- Consumes: `support_kb.kb_text`, `support_bot.answer`, `optional_current_user`, `default_limit`, `require_turnstile`, `get_db`, models `SupportTicket`/`SupportMessage`.
- Produces routes: `GET /support/kb`, `POST /support/chat`. Chat request `{question: str, history?: list, ticket_id?: uuid}`; response `{answer, answered, ticket_id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_support_chat.py
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select

from backend.config import settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _stub_bot(monkeypatch):
    from backend.services import support_bot

    async def fake(question, history, audience, plan=None):
        if "stuck" in question:
            return {"answer": "not sure, team will follow up", "answered": False}
        return {"answer": "Starter is 5,999.", "answered": True}

    monkeypatch.setattr(support_bot, "answer", fake)


async def test_public_chat_answers_and_logs_ai_resolved(client, db):
    from backend.models.schema import SupportTicket
    r = await client.post("/support/chat", json={"question": "cost of starter?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answered"] is True and "5,999" in body["answer"]
    tid = uuid.UUID(body["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert row.status == "ai_resolved"
    assert row.org_id is None  # public


async def test_unanswered_chat_logs_open_ticket(client, db):
    from backend.models.schema import SupportTicket
    r = await client.post("/support/chat", json={"question": "I am stuck, help"})
    tid = uuid.UUID(r.json()["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert row.status == "open"


async def test_authed_chat_ticket_carries_org(client, db):
    from backend.models.schema import Organization, SupportTicket
    org = Organization(name="C", owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                        plan="clinic", status="active")
    db.add(org)
    await db.commit()
    now = datetime.now(timezone.utc)
    tok = jwt.encode({"sub": str(uuid.uuid4()), "email": "o@t.com", "role": "org_admin",
                      "org_id": str(org.id), "branch_ids": [], "is_admin": False,
                      "iat": int(now.timestamp()),
                      "exp": int((now + timedelta(hours=8)).timestamp()),
                      "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")
    r = await client.post("/support/chat", json={"question": "cost?"},
                          headers={"Authorization": f"Bearer {tok}"})
    tid = uuid.UUID(r.json()["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert str(row.org_id) == str(org.id)
    assert row.source == "in_app"


async def test_chat_question_length_capped(client):
    r = await client.post("/support/chat", json={"question": "x" * 5000})
    assert r.status_code == 422


async def test_kb_public_subset(client):
    r = await client.get("/support/kb")
    assert r.status_code == 200
    assert "Connecting your phone number" not in r.text  # clinic-only stays out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_support_chat.py -q`
Expected: FAIL — 404 (route not mounted).

- [ ] **Step 3: Write the router**

`backend/routers/support.py`:

```python
"""Support: KB read + grounded chatbot that auto-logs a ticket per chat.

RULE 1: bot has no clinic-data access; authed tickets carry the caller's org.
RULE 8: bot failure returns a safe refusal, never a 500.
RULE 9: log ticket/message IDs, never bodies.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import optional_current_user
from backend.middleware.rate_limit import default_limit
from backend.models.schema import SupportMessage, SupportTicket
from backend.services import support_bot, support_kb
from backend.services.turnstile import require_turnstile

logger = structlog.get_logger()
router = APIRouter()


class ChatTurn(BaseModel):
    role: str = Field("user", max_length=16)
    content: str = Field("", max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    ticket_id: uuid.UUID | None = None


@router.get("/kb")
async def get_kb(request: Request):
    user = await optional_current_user(request)
    audience = "clinic" if user and user.org_id else "public"
    return {"audience": audience, "markdown": support_kb.kb_text(audience)}


@router.post("/chat", dependencies=[Depends(default_limit), Depends(require_turnstile)])
async def chat(body: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await optional_current_user(request)
    audience = "clinic" if user and user.org_id else "public"
    result = await support_bot.answer(
        body.question, [t.model_dump() for t in body.history], audience,
        plan=None,  # plan lookup deferred; RULE 1 keeps bot clinic-data-free
    )

    # One ticket per chat SESSION: reuse ticket_id if the client passed one AND
    # it belongs to this caller; else open a new one.
    ticket = None
    if body.ticket_id:
        q = select(SupportTicket).where(SupportTicket.id == body.ticket_id)
        ticket = (await db.execute(q)).scalar_one_or_none()
        if ticket and (str(ticket.org_id or "") != str((user.org_id if user else "") or "")):
            ticket = None  # not this caller's ticket → new one
    if ticket is None:
        ticket = SupportTicket(
            org_id=(user.org_id if user else None),
            email=(user.email if user else "anonymous@vachanam.in"),
            subject=body.question[:200],
            category="other",
            status="ai_resolved" if result["answered"] else "open",
            priority="normal",
            source="in_app" if (user and user.org_id) else "public_chat",
        )
        db.add(ticket)
        await db.flush()
    else:
        # follow-up turn: an unanswered turn re-opens an ai_resolved ticket
        if not result["answered"] and ticket.status == "ai_resolved":
            ticket.status = "open"

    db.add_all([
        SupportMessage(ticket_id=ticket.id, sender="user", body=body.question),
        SupportMessage(ticket_id=ticket.id, sender="bot", body=result["answer"]),
    ])
    await db.commit()
    logger.info("support_chat", ticket_id=str(ticket.id), answered=result["answered"],
                org_id=str(ticket.org_id) if ticket.org_id else None)
    return {"answer": result["answer"], "answered": result["answered"],
            "ticket_id": str(ticket.id)}
```

Mount in `backend/main.py` (with the other `include_router` calls, ~line 342):

```python
from backend.routers import support as support_router
app.include_router(support_router.router, prefix="/support", tags=["support"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_support_chat.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/support.py backend/main.py tests/integration/test_support_chat.py
git commit -m "feat(support): /support/kb + /support/chat auto-logs ticket (ai_resolved/open)"
```

---

### Task 7: Ticket reads — org-scoped list + thread (IDOR-safe)

**Files:**
- Modify: `backend/routers/support.py`
- Test: `tests/security/test_support_ticket_idor.py`

**Interfaces:**
- Consumes: `get_current_user` (auth required here), models.
- Produces routes: `GET /support/tickets` (caller's org), `GET /support/tickets/{id}` + `GET /support/tickets/{id}/messages` (404 if not caller's org).

- [ ] **Step 1: Write the failing test**

```python
# tests/security/test_support_ticket_idor.py
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _tok(org_id):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(uuid.uuid4()), "email": "o@t.com", "role": "org_admin",
                       "org_id": str(org_id), "branch_ids": [], "is_admin": False,
                       "iat": int(now.timestamp()),
                       "exp": int((now + timedelta(hours=8)).timestamp()),
                       "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")


async def _mk(db, tag):
    from backend.models.schema import Organization, SupportTicket, SupportMessage
    org = Organization(name=tag, owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    t = SupportTicket(org_id=org.id, email="o@t.com", subject="s", category="other",
                      status="open", priority="normal", source="in_app")
    db.add(t)
    await db.flush()
    db.add(SupportMessage(ticket_id=t.id, sender="user", body="secret body A"))
    await db.commit()
    return str(org.id), str(t.id)


async def test_clinic_cannot_read_another_clinics_ticket(client, db):
    a_org, a_ticket = await _mk(db, "A")
    b_org, _ = await _mk(db, "B")
    tokB = _tok(b_org)
    # B lists → only B's tickets, never A's
    r = await client.get("/support/tickets", headers={"Authorization": f"Bearer {tokB}"})
    assert r.status_code == 200 and a_ticket not in r.text
    # B fetches A's ticket by id → 404
    r = await client.get(f"/support/tickets/{a_ticket}", headers={"Authorization": f"Bearer {tokB}"})
    assert r.status_code == 404
    # B reads A's thread → 404, never "secret body A"
    r = await client.get(f"/support/tickets/{a_ticket}/messages",
                         headers={"Authorization": f"Bearer {tokB}"})
    assert r.status_code == 404 and "secret body A" not in r.text


async def test_owner_reads_own_ticket_thread(client, db):
    org, ticket = await _mk(db, "own")
    tok = _tok(org)
    r = await client.get(f"/support/tickets/{ticket}/messages",
                         headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and "secret body A" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/security/test_support_ticket_idor.py -q`
Expected: FAIL — 404/405 (routes not defined).

- [ ] **Step 3: Add the read routes to `backend/routers/support.py`**

Add imports at top: `from fastapi import HTTPException` (extend existing fastapi import) and `from backend.middleware.auth_middleware import CurrentUser, get_current_user`. Append:

```python
async def _my_ticket(ticket_id: uuid.UUID, user: CurrentUser, db: AsyncSession) -> SupportTicket:
    q = select(SupportTicket).where(
        SupportTicket.id == ticket_id, SupportTicket.org_id == user.org_id
    )
    t = (await db.execute(q)).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@router.get("/tickets")
async def list_my_tickets(user: CurrentUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(SupportTicket).where(SupportTicket.org_id == user.org_id)
        .order_by(SupportTicket.created_at.desc())
    )).scalars().all()
    return [{"id": str(t.id), "subject": t.subject, "status": t.status,
             "category": t.category, "created_at": t.created_at.isoformat()} for t in rows]


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    t = await _my_ticket(ticket_id, user, db)
    return {"id": str(t.id), "subject": t.subject, "status": t.status,
            "category": t.category, "created_at": t.created_at.isoformat()}


@router.get("/tickets/{ticket_id}/messages")
async def get_ticket_messages(ticket_id: uuid.UUID,
                              user: CurrentUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    await _my_ticket(ticket_id, user, db)  # 404s if not caller's org
    rows = (await db.execute(
        select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
        .order_by(SupportMessage.created_at.asc())
    )).scalars().all()
    return [{"sender": m.sender, "body": m.body, "created_at": m.created_at.isoformat()}
            for m in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/security/test_support_ticket_idor.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/support.py tests/security/test_support_ticket_idor.py
git commit -m "feat(support): org-scoped ticket list + thread reads (IDOR-safe)"
```

---

### Task 8: Full-suite gate (backend done)

**Files:** none (verification task).

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: all green (previous 879 passed + the new support tests; 3 pre-existing skips). If any pre-existing test broke, fix the cause (do not weaken the test).

- [ ] **Step 2: Commit (only if a fix was needed)**

```bash
git commit -am "test(support): keep full suite green"
```

---

### Task 9: Frontend — support API client

**Files:**
- Create: `frontend/src/api/support.js`
- Test: build gate only.

**Interfaces:**
- Consumes: the shared axios instance (`frontend/src/api/client.js` — JWT interceptor already attaches the token).
- Produces: `getKb()`, `sendChat({question, history, ticketId})`, `listTickets()`, `getTicketMessages(id)`.

- [ ] **Step 1: Write the client**

```javascript
// frontend/src/api/support.js
import client from "./client";

export const getKb = () => client.get("/support/kb").then((r) => r.data);

export const sendChat = ({ question, history = [], ticketId = null }) =>
  client
    .post("/support/chat", { question, history, ticket_id: ticketId })
    .then((r) => r.data);

export const listTickets = () => client.get("/support/tickets").then((r) => r.data);

export const getTicketMessages = (id) =>
  client.get(`/support/tickets/${id}/messages`).then((r) => r.data);
```

> Confirm `frontend/src/api/client.js` exports a default axios instance; if it exports `{ api }` named, match that import style.

- [ ] **Step 2: Build gate**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/support.js
git commit -m "feat(support): frontend support API client"
```

---

### Task 10: Frontend — Help page (KB search + chat widget)

**Files:**
- Create: `frontend/src/pages/Help.jsx`
- Modify: `frontend/src/App.jsx` (route), Shell nav (in-app link), Landing (public link)
- Test: build gate + manual.

**Interfaces:**
- Consumes: `getKb`, `sendChat`.
- Produces: a `/help` route usable logged-out (public KB) and logged-in (clinic KB). Chat widget keeps `ticket_id` across turns so one session = one ticket.

- [ ] **Step 1: Write the page**

```jsx
// frontend/src/pages/Help.jsx
import { useEffect, useRef, useState } from "react";
import { getKb, sendChat } from "../api/support";

export default function Help() {
  const [kb, setKb] = useState("");
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState([]); // {role, content}
  const [ticketId, setTicketId] = useState(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    getKb().then((d) => setKb(d.markdown)).catch(() => setKb(""));
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  const ask = async (e) => {
    e.preventDefault();
    const question = q.trim();
    if (!question || busy) return;
    setBusy(true);
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: question }]);
    setQ("");
    try {
      const res = await sendChat({ question, history, ticketId });
      setTicketId(res.ticket_id);
      setMsgs((m) => [...m, { role: "bot", content: res.answer }]);
    } catch {
      setMsgs((m) => [
        ...m,
        { role: "bot", content: "Something went wrong — email hello@vachanam.in and we'll help." },
      ]);
    } finally {
      setBusy(false);
    }
  };

  // Simple client-side KB search (corpus is small).
  const [filter, setFilter] = useState("");
  const kbShown = filter
    ? kb
        .split(/\n(?=## )/)
        .filter((s) => s.toLowerCase().includes(filter.toLowerCase()))
        .join("\n")
    : kb;

  return (
    <div className="max-w-3xl mx-auto p-4 space-y-6 text-ink">
      <h1 className="text-2xl font-semibold">Help &amp; support</h1>

      <section className="space-y-2">
        <input
          className="w-full rounded-lg border px-3 py-2 bg-surface"
          placeholder="Search help articles…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <article className="prose prose-sm max-w-none whitespace-pre-wrap bg-surface rounded-lg p-4 border">
          {kbShown || "No articles found."}
        </article>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">Ask the assistant</h2>
        <div className="border rounded-lg p-3 h-80 overflow-y-auto bg-surface space-y-2">
          {msgs.length === 0 && (
            <p className="text-sm opacity-70">Ask anything about Vachanam — pricing, setup, calls.</p>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
              <span
                className={
                  "inline-block rounded-2xl px-3 py-2 text-sm " +
                  (m.role === "user" ? "bg-teal text-white" : "bg-cell-empty")
                }
              >
                {m.content}
              </span>
            </div>
          ))}
          <div ref={endRef} />
        </div>
        <form onSubmit={ask} className="flex gap-2">
          <input
            className="flex-1 rounded-lg border px-3 py-2 bg-surface"
            placeholder="Type your question…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="btn-primary" disabled={busy}>
            {busy ? "…" : "Send"}
          </button>
        </form>
      </section>
    </div>
  );
}
```

> Use whatever token classes the app already defines (`text-ink`, `bg-surface`, `bg-teal`, `bg-cell-empty`, `btn-primary` come from the #311 dark-mode token set — confirm the exact names in `frontend/src/index.css` and adjust). The page must work in both themes.

- [ ] **Step 2: Wire routes/nav**

- In `frontend/src/App.jsx`: add a `<Route path="/help" element={<Help />} />` OUTSIDE the auth-guarded block (public), importing `Help`.
- In the Shell/nav component: add a "Help" link to `/help` for logged-in users.
- In `frontend/src/pages/Landing.jsx`: add a "Help / Support" link to `/help`.

- [ ] **Step 3: Build gate**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual check**

`npm run dev`, open `/help` logged-out → KB loads (public subset), ask a question → answer appears, one ticket logged. Log in → `/help` shows clinic KB. Toggle dark mode → readable.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Help.jsx frontend/src/App.jsx frontend/src/pages/Landing.jsx frontend/src/components
git commit -m "feat(support): Help page — KB search + chat widget (public + in-app)"
```

---

### Task 11: Frontend — My Tickets log + thread

**Files:**
- Create: `frontend/src/pages/MyTickets.jsx`
- Modify: `frontend/src/App.jsx` (auth-guarded route), Shell nav
- Test: build gate + manual.

**Interfaces:**
- Consumes: `listTickets`, `getTicketMessages`.
- Produces: `/tickets` (auth-guarded) — a list of the clinic's tickets with status chips; click opens the read-only thread (replies are Phase 2).

- [ ] **Step 1: Write the page**

```jsx
// frontend/src/pages/MyTickets.jsx
import { useEffect, useState } from "react";
import { listTickets, getTicketMessages } from "../api/support";

const STATUS_LABEL = {
  ai_resolved: "Answered by assistant",
  open: "With our team",
  pending: "Awaiting your reply",
  resolved: "Resolved",
  closed: "Closed",
};

export default function MyTickets() {
  const [tickets, setTickets] = useState([]);
  const [active, setActive] = useState(null);
  const [thread, setThread] = useState([]);

  useEffect(() => {
    listTickets().then(setTickets).catch(() => setTickets([]));
  }, []);
  useEffect(() => {
    if (active) getTicketMessages(active).then(setThread).catch(() => setThread([]));
  }, [active]);

  return (
    <div className="max-w-3xl mx-auto p-4 space-y-4 text-ink">
      <h1 className="text-2xl font-semibold">My support tickets</h1>
      {tickets.length === 0 && <p className="opacity-70">No tickets yet.</p>}
      <ul className="space-y-2">
        {tickets.map((t) => (
          <li key={t.id}>
            <button
              className="w-full text-left border rounded-lg p-3 bg-surface hover:brightness-95"
              onClick={() => setActive(active === t.id ? null : t.id)}
            >
              <div className="flex justify-between gap-2">
                <span className="font-medium truncate">{t.subject}</span>
                <span className="text-xs rounded-full px-2 py-0.5 bg-cell-empty whitespace-nowrap">
                  {STATUS_LABEL[t.status] || t.status}
                </span>
              </div>
              <div className="text-xs opacity-60">{new Date(t.created_at).toLocaleString()}</div>
            </button>
            {active === t.id && (
              <div className="border-x border-b rounded-b-lg p-3 bg-surface space-y-2">
                {thread.map((m, i) => (
                  <div key={i} className={m.sender === "user" ? "text-right" : "text-left"}>
                    <span
                      className={
                        "inline-block rounded-2xl px-3 py-2 text-sm " +
                        (m.sender === "user" ? "bg-teal text-white" : "bg-cell-empty")
                      }
                    >
                      {m.body}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Wire route/nav**

- `frontend/src/App.jsx`: add `<Route path="/tickets" element={<MyTickets />} />` INSIDE the auth-guarded block.
- Shell nav: add a "My Tickets" link to `/tickets`.

- [ ] **Step 3: Build gate**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual check**

Log in, open `/help`, ask 2 questions → open `/tickets` → both sessions show with correct status chips; expand → thread shows user+bot turns. Confirm another clinic's tickets never appear (already enforced server-side).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MyTickets.jsx frontend/src/App.jsx frontend/src/components
git commit -m "feat(support): My Tickets log + thread view (in-app)"
```

---

### Task 12: FIXLOG + STATUS + docs

**Files:**
- Modify: `docs/FIXLOG.md`, `docs/STATUS.md`
- Test: none.

- [ ] **Step 1: Add a FIXLOG row** (next number after the current head, `#314`):

```
| 314 | 07-11 | Support system Phase 1 (Vinay: "support page + AI chatbot + ticket logs"). | No support surface existed for clinics — only the per-clinic patient FAQ. | KB (docs/support/*.md, audience-filtered) + /support/kb + /support/chat (Gemini-flash-lite grounded, RULE 1 no clinic-data, RULE 8 safe refusal) auto-logging one ticket per chat (answered→ai_resolved, stuck→open); support_tickets+support_messages (additive migration aa24, DEPLOY-GATED); org-scoped ticket reads; Help page (KB search + chat, public+in-app) + My Tickets thread. | ✅ test_support_models, test_support_kb, test_support_bot, test_optional_auth, test_support_chat (6), test_support_ticket_idor (IDOR wall). Full suite green. npm run build green. Migration NOT yet applied to prod. |
```

- [ ] **Step 2: Update `docs/STATUS.md`** — note Phase 1 support shipped to master (code), migration aa24 deploy-gated, Phase 2 (support role + admin dashboard + replies/email) next.

- [ ] **Step 3: Commit + push**

```bash
git add docs/FIXLOG.md docs/STATUS.md
git commit -m "docs(support): FIXLOG #314 + STATUS for support Phase 1"
git push origin master
```

> Render auto-deploys the backend. The migration is NOT applied — the new routes work only after Vinay applies `aa24` to prod (the `/support/*` routes will 500 on the missing tables until then; acceptable — gated). Confirm with Vinay before applying.

---

## Self-Review

**1. Spec coverage (Phase 1 scope):**
- KB corpus + audience filter → Task 3 ✓
- `/support/kb` → Task 6 ✓
- `/support/chat` grounded, public+authed, rate-limited, Turnstile, auto-log ticket ai_resolved/open → Tasks 4,5,6 ✓
- support_tickets + support_messages migration (deploy-gated) → Tasks 1,2 ✓
- My Tickets log/thread (clinic-facing, org-scoped) → Tasks 7,11 ✓
- Public /help + in-app Help page → Task 10 ✓
- RULE 1 (bot no clinic data; tickets org-scoped) → Task 4 (no tool access) + Task 7 (IDOR test) ✓
- RULE 8 (bot safe refusal) → Task 4 ✓
- RULE 9 (log IDs not bodies) → Task 6 logger call ✓
- Bounded inputs → Task 6 Pydantic Fields ✓
- `"support"` role value (no route yet) → Task 1 ✓

**2. Placeholder scan:** `<PRIOR_HEAD>` in Task 2 is filled from the Step-1 command output (a real value, not a plan placeholder). Token class names in frontend flagged for confirmation against index.css. No TODO/TBD logic gaps.

**3. Type consistency:** `answer()` returns `{answer, answered}` — consumed identically in Task 6. `optional_current_user` returns `CurrentUser | None` — Task 6 checks `user and user.org_id`. `kb_text(audience)` signature consistent Tasks 3/4/6. Ticket status strings (`ai_resolved`/`open`) consistent across models, router, tests, frontend labels.

**Deferred to Phase 2 (not gaps):** `support` role routes + provisioning, staff replies, live-chat polling, email notifications, admin dashboard. Phase 3: CSAT, SLA/escalation job, macros, demo form, status link.
