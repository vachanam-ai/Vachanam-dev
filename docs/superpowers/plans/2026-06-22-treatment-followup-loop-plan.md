# Treatment Progress + Follow-up Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record patient treatment visit-by-visit and run a two-way, voice-mediated doctor↔patient follow-up loop (agent relays the doctor's questions/advice and books the next visit; never advises).

**Architecture:** New `treatment_notes` table (operational notes, dashboard-only) + a follow-up thread built by reusing `FollowupTask` (extended with `treatment_note_id`). A 15-min `next_visit_followup_caller` job (09:00–20:00 IST) dispatches outbound calls via the existing reminder dispatch path; new agent `call_type`s `next_visit_book` / `doctor_advice` relay doctor-authored messages, capture replies, and book within ±2 days using the existing booking tools. Split into M1 (notes + dashboard) and M2 (the call loop).

**Tech Stack:** FastAPI + SQLAlchemy 2.x async + Alembic + Pydantic; APScheduler; LiveKit Agents 1.6; React 18 + Vite PWA + TanStack Query + axios; pytest (async `db` fixture on `vachanam_test`).

## Global Constraints

- **RULE 1 (tenant isolation):** every table + query is `branch_id`-scoped; super_admin denied on all these routes (`forbid_admin` + `assert_branch_access`). Three-layer isolation: middleware + handler JWT `branch_ids` + DB `WHERE branch_id=?`.
- **RULE 2 (no double-booking):** booking only via the existing atomic Redis token-assign path; never derive a token from a count.
- **RULE 6:** doctor messages go to the LLM as context, never raw to TTS.
- **RULE 7:** agent relays doctor content verbatim; composes no advice/triage/diagnosis; no "108"; intent-based human transfer only.
- **RULE 9:** `steps_performed`/`next_steps` and the thread's health text are `branch_id`-scoped, erased with the patient, never sent to calendar/SMS, and the agent metadata carries **no** private notes.
- **Proof per task (Vinay standing rule):** every task ships a regression test that fails before and passes after, a `docs/FIXLOG.md` row, and the FULL suite re-run green (minus the known pre-existing env failures: 7 DB-fixture errors when no local Postgres + 1 live-smallest.ai clone 500).
- **Auth deps (exact):** `from backend.middleware.auth_middleware import CurrentUser, get_current_user, forbid_admin`; `from backend.middleware.branch_guard import assert_branch_access`. `CurrentUser` fields: `user_id, email, role, org_id, branch_ids, is_admin`.
- **Migrations:** additive only; `down_revision` = current `alembic heads` at execution time. New DBs are provisioned via `create_all` + stamp head (broken upgrade-from-base chain — see memory `project-alembic-chain-broken`).

---

# MILESTONE M1 — Treatment notes + dashboard

## Task 1: `treatment_notes` model + migration

**Files:**
- Modify: `backend/models/schema.py` (add `TreatmentNote`; add relationship on `Patient`/`Doctor`/`Branch` if the pattern requires — match existing `FollowupTask` relationship style)
- Create: `alembic/versions/<rev>_treatment_notes.py`
- Test: `tests/unit/test_treatment_note_model.py`

**Interfaces:**
- Produces: `TreatmentNote` ORM class with columns `id, branch_id, doctor_id, patient_id, token_id(nullable), visit_date, steps_performed(nullable), next_steps(nullable), next_reporting_date(nullable), is_final(bool default False), created_by_user_id(nullable), created_at, updated_at`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_treatment_note_model.py`

```python
import uuid
from datetime import date
import pytest
from sqlalchemy import select
from backend.models.schema import TreatmentNote, Branch, Doctor, Patient


@pytest.mark.asyncio
async def test_treatment_note_persists_and_defaults(db):
    br = Branch(id=uuid.uuid4(), org_id=uuid.uuid4(), name="C", did_number="+910000000001")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000001")
    db.add_all([doc, pat]); await db.flush()
    note = TreatmentNote(
        branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
        visit_date=date(2026, 6, 22), steps_performed="cleaning",
        next_steps="floss", next_reporting_date=date(2026, 6, 25),
    )
    db.add(note); await db.flush()
    row = (await db.execute(select(TreatmentNote).where(TreatmentNote.id == note.id))).scalar_one()
    assert row.is_final is False
    assert row.branch_id == br.id and row.next_reporting_date == date(2026, 6, 25)
```

- [ ] **Step 2: Run — expect FAIL** `pytest tests/unit/test_treatment_note_model.py -v` → `ImportError: cannot import name 'TreatmentNote'`

- [ ] **Step 3: Implement** — add to `backend/models/schema.py` (place near `FollowupTask`; mirror its column idioms — `Mapped`, `mapped_column`, RESTRICT FKs, `func.now()`):

```python
class TreatmentNote(Base):
    __tablename__ = "treatment_notes"
    __table_args__ = (
        Index("ix_treatment_notes_branch_patient_date", "branch_id", "patient_id", "visit_date"),
        Index("ix_treatment_notes_branch_doctor", "branch_id", "doctor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tokens.id", ondelete="RESTRICT"), nullable=True, index=True)
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    steps_performed: Mapped[str | None] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text)
    next_reporting_date: Mapped[date | None] = mapped_column(Date)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: Create migration** — `alembic heads` to get the current head; create `alembic/versions/<rev>_treatment_notes.py` (mirror the `q14callscore2026` file shape):

```python
"""treatment_notes table (treatment progress notes).

Revision ID: r15treatmentnotes2026
Revises: <CURRENT_HEAD_FROM_alembic_heads>
Create Date: 2026-06-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "r15treatmentnotes2026"
down_revision = "<CURRENT_HEAD>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "treatment_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("doctor_id", UUID(as_uuid=True), sa.ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_id", UUID(as_uuid=True), sa.ForeignKey("tokens.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("steps_performed", sa.Text(), nullable=True),
        sa.Column("next_steps", sa.Text(), nullable=True),
        sa.Column("next_reporting_date", sa.Date(), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_treatment_notes_branch_id", "treatment_notes", ["branch_id"])
    op.create_index("ix_treatment_notes_doctor_id", "treatment_notes", ["doctor_id"])
    op.create_index("ix_treatment_notes_patient_id", "treatment_notes", ["patient_id"])
    op.create_index("ix_treatment_notes_token_id", "treatment_notes", ["token_id"])
    op.create_index("ix_treatment_notes_branch_patient_date", "treatment_notes", ["branch_id", "patient_id", "visit_date"])
    op.create_index("ix_treatment_notes_branch_doctor", "treatment_notes", ["branch_id", "doctor_id"])


def downgrade() -> None:
    op.drop_table("treatment_notes")
```

- [ ] **Step 5: Run — expect PASS** `pytest tests/unit/test_treatment_note_model.py -v`

- [ ] **Step 6: FIXLOG + full suite + commit**

```bash
# Append a docs/FIXLOG.md row: treatment_notes model+migration, regression test_treatment_note_model.
pytest tests/unit -q   # expect prior green + new test pass (known env failures excepted)
git add backend/models/schema.py alembic/versions/ tests/unit/test_treatment_note_model.py docs/FIXLOG.md
git commit -m "feat(treatment): treatment_notes model + migration"
```

---

## Task 2: completion helper (`is_final` from button OR `end` keyword)

**Files:**
- Create: `backend/services/treatment_logic.py`
- Test: `tests/unit/test_treatment_logic.py`

**Interfaces:**
- Produces: `resolve_is_final(is_final_flag: bool | None, next_steps: str | None) -> bool`

- [ ] **Step 1: Write the failing test** — `tests/unit/test_treatment_logic.py`

```python
from backend.services.treatment_logic import resolve_is_final


def test_button_sets_final():
    assert resolve_is_final(True, "keep going") is True

def test_end_keyword_sets_final_case_insensitive():
    assert resolve_is_final(False, "  END ") is True
    assert resolve_is_final(None, "end") is True

def test_partial_word_does_not_close():
    assert resolve_is_final(False, "treatment ending soon") is False
    assert resolve_is_final(None, "send report") is False

def test_default_open():
    assert resolve_is_final(None, None) is False
    assert resolve_is_final(False, "floss daily") is False
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** — `backend/services/treatment_logic.py`

```python
"""Pure logic for treatment-note state. No DB, fully unit-testable."""
from __future__ import annotations


def resolve_is_final(is_final_flag: bool | None, next_steps: str | None) -> bool:
    """Treatment is complete if the 'Mark complete' button sent it, OR the doctor
    typed exactly 'end' as the next step (case-insensitive, whitespace-trimmed).
    A partial match like 'ending soon' or 'send' must NOT close it."""
    if is_final_flag:
        return True
    return (next_steps or "").strip().lower() == "end"
```

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: FIXLOG + commit** (`feat(treatment): completion resolver (button + 'end' keyword)`)

---

## Task 3: treatment router — notes CRUD + dropdown + timeline

**Files:**
- Create: `backend/routers/treatment.py`
- Test: `tests/integration/test_treatment_notes_api.py`

**Interfaces:**
- Consumes: `resolve_is_final` (Task 2); `TreatmentNote` (Task 1); `assert_branch_access`, `get_current_user`, `forbid_admin`.
- Produces: `router` with `GET /branches/{branch_id}/treatment-patients`, `GET /patients/{patient_id}/treatment-notes`, `POST /patients/{patient_id}/treatment-notes`, `PATCH /treatment-notes/{note_id}`. **No enqueue logic in M1** (added in Task 7).

- [ ] **Step 1: Write the failing test** — `tests/integration/test_treatment_notes_api.py`

```python
import uuid
from datetime import date
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.models.schema import Branch, Doctor, Patient
from backend.middleware.auth_middleware import get_current_user, CurrentUser


def _as_user(branch_id, org_id, role="org_admin"):
    return CurrentUser(user_id=str(uuid.uuid4()), email="d@c.com", role=role,
                       org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False)


@pytest.mark.asyncio
async def test_create_and_list_treatment_note(db):
    org_id = uuid.uuid4()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", did_number="+910000000010")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000010")
    db.add_all([doc, pat]); await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/treatment-notes", json={
                "doctor_id": str(doc.id), "branch_id": str(br.id),
                "visit_date": "2026-06-22", "steps_performed": "cleaning",
                "next_steps": "floss", "next_reporting_date": "2026-06-25"})
            assert r.status_code == 201, r.text
            assert r.json()["is_final"] is False

            r2 = await ac.get(f"/treatment/patients/{pat.id}/treatment-notes",
                              params={"branch_id": str(br.id)})
            assert r2.status_code == 200
            body = r2.json()
            assert body["treatment_status"] == "active"
            assert len(body["notes"]) == 1


@pytest.mark.asyncio
async def test_end_keyword_closes_treatment(db):
    org_id = uuid.uuid4()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", did_number="+910000000011")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000011")
    db.add_all([doc, pat]); await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/treatment-notes", json={
                "doctor_id": str(doc.id), "branch_id": str(br.id),
                "visit_date": "2026-06-22", "next_steps": "end"})
            assert r.json()["is_final"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cross_branch_note_denied(db):
    org_id = uuid.uuid4()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", did_number="+910000000012")
    other = Branch(id=uuid.uuid4(), org_id=uuid.uuid4(), name="O", did_number="+910000000013")
    db.add_all([br, other]); await db.flush()
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000012")
    db.add(pat); await db.commit()
    # User scoped to `other` must not write a note on br's patient.
    app.dependency_overrides[get_current_user] = lambda: _as_user(other.id, other.org_id)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/treatment-notes", json={
                "doctor_id": str(uuid.uuid4()), "branch_id": str(br.id),
                "visit_date": "2026-06-22"})
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run — expect FAIL** (404/route missing)

- [ ] **Step 3: Implement** — `backend/routers/treatment.py` (follow `queue.py` idioms: `get_db`, `assert_branch_access`, branch-filtered queries; `forbid_admin` dependency on the router):

```python
"""Treatment progress notes (M1) + follow-up thread (M2).

RULE 1: every route is branch-scoped (assert_branch_access) and super_admin is
denied (forbid_admin). steps_performed/next_steps are operational notes —
dashboard-only, never spoken or sent to calendar/SMS (RULE 9).
"""
import uuid
from datetime import date
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user, forbid_admin
from backend.middleware.branch_guard import assert_branch_access
from backend.models.schema import TreatmentNote, Patient, Doctor, Token
from backend.services.treatment_logic import resolve_is_final

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(forbid_admin)])


class NoteIn(BaseModel):
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    visit_date: date
    token_id: uuid.UUID | None = None
    steps_performed: str | None = Field(None, max_length=4000)
    next_steps: str | None = Field(None, max_length=2000)
    next_reporting_date: date | None = None
    is_final: bool | None = None

    @field_validator("visit_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("visit_date cannot be in the future")
        return v


class NoteOut(BaseModel):
    id: uuid.UUID
    visit_date: date
    steps_performed: str | None
    next_steps: str | None
    next_reporting_date: date | None
    is_final: bool
    doctor_id: uuid.UUID


async def _load_patient(patient_id: uuid.UUID, branch_id: uuid.UUID, db: AsyncSession) -> Patient:
    pat = (await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.branch_id == branch_id)
    )).scalar_one_or_none()
    if pat is None:
        raise HTTPException(status_code=404, detail="patient not found in branch")
    return pat


@router.post("/patients/{patient_id}/treatment-notes", status_code=201, response_model=NoteOut)
async def create_note(patient_id: uuid.UUID, body: NoteIn,
                      user: CurrentUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await assert_branch_access(user, str(body.branch_id), db)
    await _load_patient(patient_id, body.branch_id, db)
    if body.next_reporting_date and body.next_reporting_date < body.visit_date:
        raise HTTPException(status_code=422, detail="next_reporting_date before visit_date")
    note = TreatmentNote(
        branch_id=body.branch_id, doctor_id=body.doctor_id, patient_id=patient_id,
        token_id=body.token_id, visit_date=body.visit_date,
        steps_performed=body.steps_performed, next_steps=body.next_steps,
        next_reporting_date=body.next_reporting_date,
        is_final=resolve_is_final(body.is_final, body.next_steps),
        created_by_user_id=uuid.UUID(user.user_id) if user.user_id else None,
    )
    db.add(note); await db.commit(); await db.refresh(note)
    # M2 (Task 7) hooks enqueue/cancel here.
    return note


@router.patch("/treatment-notes/{note_id}", response_model=NoteOut)
async def edit_note(note_id: uuid.UUID, body: NoteIn,
                    user: CurrentUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await assert_branch_access(user, str(body.branch_id), db)
    note = (await db.execute(
        select(TreatmentNote).where(TreatmentNote.id == note_id,
                                    TreatmentNote.branch_id == body.branch_id)
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    note.steps_performed = body.steps_performed
    note.next_steps = body.next_steps
    note.next_reporting_date = body.next_reporting_date
    note.is_final = resolve_is_final(body.is_final, body.next_steps)
    await db.commit(); await db.refresh(note)
    return note


@router.get("/patients/{patient_id}/treatment-notes")
async def list_notes(patient_id: uuid.UUID, branch_id: uuid.UUID,
                     user: CurrentUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    await assert_branch_access(user, str(branch_id), db)
    rows = (await db.execute(
        select(TreatmentNote).where(TreatmentNote.patient_id == patient_id,
                                    TreatmentNote.branch_id == branch_id)
        .order_by(TreatmentNote.visit_date.asc(), TreatmentNote.created_at.asc())
    )).scalars().all()
    status = "completed" if (rows and rows[-1].is_final) else ("active" if rows else "none")
    return {"treatment_status": status,
            "notes": [NoteOut.model_validate(r, from_attributes=True).model_dump(mode="json") for r in rows]}


@router.get("/branches/{branch_id}/treatment-patients")
async def list_patients(branch_id: uuid.UUID, doctor_id: uuid.UUID | None = None,
                        status: str = "all",
                        user: CurrentUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await assert_branch_access(user, str(branch_id), db)
    # Latest note per patient (branch-scoped) drives active/last-visit/next-date.
    q = select(TreatmentNote).where(TreatmentNote.branch_id == branch_id)
    if doctor_id:
        q = q.where(TreatmentNote.doctor_id == doctor_id)
    notes = (await db.execute(q.order_by(TreatmentNote.patient_id,
             TreatmentNote.visit_date.asc(), TreatmentNote.created_at.asc()))).scalars().all()
    latest: dict[uuid.UUID, TreatmentNote] = {}
    for n in notes:
        latest[n.patient_id] = n  # last wins = newest
    pat_ids = list(latest.keys())
    if not pat_ids:
        return {"patients": []}
    pats = {p.id: p for p in (await db.execute(
        select(Patient).where(Patient.id.in_(pat_ids)))).scalars().all()}
    out = []
    for pid, n in latest.items():
        active = not n.is_final
        if status == "active" and not active:
            continue
        p = pats.get(pid)
        if p is None:
            continue
        out.append({"patient_id": str(pid), "name": p.name,
                    "phone_last4": (p.phone or "")[-4:], "doctor_id": str(n.doctor_id),
                    "last_visit_date": n.visit_date.isoformat(),
                    "next_reporting_date": n.next_reporting_date.isoformat() if n.next_reporting_date else None,
                    "active": active})
    return {"patients": out}
```

- [ ] **Step 4: Register the router** — `backend/main.py` (after the other `include_router` lines, ~line 245):

```python
from backend.routers import treatment as treatment_router
app.include_router(treatment_router.router, prefix="/treatment", tags=["treatment"])
```

- [ ] **Step 5: Run — expect PASS** `pytest tests/integration/test_treatment_notes_api.py -v`

- [ ] **Step 6: FIXLOG + full suite + commit** (`feat(treatment): notes CRUD + dropdown + timeline endpoints`)

---

## Task 4: PWA — Treatments view (dropdown + timeline + add note + mark complete)

**Files:**
- Create: `frontend/src/pages/Treatments.jsx`
- Create: `frontend/src/api/treatment.js`
- Modify: `frontend/src/App.jsx` (add a guarded `/treatments` route, mirror the `/queue` route block)
- Modify: nav component (wherever `/queue`, `/walk-in` links live) — add a "Treatments" link for doctor/receptionist/org_admin

**Interfaces:**
- Consumes: M1 endpoints under `/treatment/...`; existing axios client `src/api/client.js` (JWT interceptor).

- [ ] **Step 1: API module** — `frontend/src/api/treatment.js`

```javascript
import { api } from "./client";

export const listTreatmentPatients = (branchId, { doctorId, status = "all" } = {}) =>
  api.get(`/treatment/branches/${branchId}/treatment-patients`, {
    params: { doctor_id: doctorId, status },
  }).then((r) => r.data.patients);

export const listNotes = (patientId, branchId) =>
  api.get(`/treatment/patients/${patientId}/treatment-notes`, {
    params: { branch_id: branchId },
  }).then((r) => r.data);

export const createNote = (patientId, payload) =>
  api.post(`/treatment/patients/${patientId}/treatment-notes`, payload).then((r) => r.data);
```

- [ ] **Step 2: Page** — `frontend/src/pages/Treatments.jsx` (TanStack Query; patient dropdown → timeline → add-note form with "Mark treatment complete" toggle; on success invalidate the notes query). Mirror the data-fetching + form patterns already in `Queue.jsx`/`WalkIn.jsx`. The add-note POST body includes `branch_id`, `doctor_id`, `visit_date` (default today), `steps_performed`, `next_steps`, `next_reporting_date`, `is_final`.

- [ ] **Step 3: Route + nav** — add to `App.jsx`:

```jsx
<Route
  path="/treatments"
  element={
    <ProtectedRoute roles={["org_admin", "doctor", "receptionist"]}>
      <Treatments />
    </ProtectedRoute>
  }
/>
```

- [ ] **Step 4: Proof (frontend has no JS test harness — manual + build)**

```bash
cd frontend && npm run build   # must succeed (no import/JSX errors)
# Manual: log in as receptionist → /treatments → pick patient → add a note with
# next_steps="end" → timeline shows it + status "Completed". Screenshot in PR.
```

- [ ] **Step 5: FIXLOG (⚠ manual UI) + commit** (`feat(treatment): PWA Treatments view`)

---

# MILESTONE M2 — The follow-up call loop

## Task 5: extend `FollowupTask` (thread link + author)

**Files:**
- Modify: `backend/models/schema.py` (add 2 columns to `FollowupTask`)
- Create: `alembic/versions/<rev>_followup_thread.py`
- Test: `tests/unit/test_followup_thread_model.py`

**Interfaces:**
- Produces: `FollowupTask.treatment_note_id: uuid | None`, `FollowupTask.created_by_user_id: uuid | None`; `task_type` now also accepts `"next_visit_book"`, `"doctor_advice"`.

- [ ] **Step 1: Failing test** — `tests/unit/test_followup_thread_model.py`

```python
import uuid
from datetime import date
import pytest
from sqlalchemy import select
from backend.models.schema import FollowupTask, Branch, Doctor, Patient, TreatmentNote


@pytest.mark.asyncio
async def test_followup_task_links_to_note(db):
    br = Branch(id=uuid.uuid4(), org_id=uuid.uuid4(), name="C", did_number="+910000000020")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000020")
    db.add_all([doc, pat]); await db.flush()
    note = TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id, visit_date=date(2026,6,22))
    db.add(note); await db.flush()
    t = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                     treatment_note_id=note.id, task_type="next_visit_book",
                     channel="voice", what_to_ask="how is your pain?",
                     scheduled_date=date(2026,6,23))
    db.add(t); await db.flush()
    row = (await db.execute(select(FollowupTask).where(FollowupTask.id == t.id))).scalar_one()
    assert row.treatment_note_id == note.id and row.task_type == "next_visit_book"
```

- [ ] **Step 2: Run — expect FAIL** (`treatment_note_id` attr missing)

- [ ] **Step 3: Implement** — add to `FollowupTask` in `backend/models/schema.py` (after the `token_id` block):

```python
    treatment_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treatment_notes.id", ondelete="RESTRICT"),
        nullable=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
```

- [ ] **Step 4: Migration** — `alembic/versions/<rev>_followup_thread.py` (revision `s16followupthread2026`, down_revision = `r15treatmentnotes2026`):

```python
def upgrade() -> None:
    op.add_column("followup_tasks", sa.Column("treatment_note_id", UUID(as_uuid=True),
        sa.ForeignKey("treatment_notes.id", ondelete="RESTRICT"), nullable=True))
    op.add_column("followup_tasks", sa.Column("created_by_user_id", UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_followup_tasks_treatment_note_id", "followup_tasks", ["treatment_note_id"])

def downgrade() -> None:
    op.drop_index("ix_followup_tasks_treatment_note_id", "followup_tasks")
    op.drop_column("followup_tasks", "created_by_user_id")
    op.drop_column("followup_tasks", "treatment_note_id")
```

- [ ] **Step 5: Run — expect PASS**; **Step 6: FIXLOG + full suite + commit** (`feat(treatment): FollowupTask thread link`)

---

## Task 6: enqueue/cancel service + wire into note POST

**Files:**
- Create: `backend/services/treatment_followup.py`
- Modify: `backend/routers/treatment.py` (call the service from `create_note`/`edit_note`)
- Test: `tests/integration/test_treatment_enqueue.py`

**Interfaces:**
- Consumes: `TreatmentNote`, `FollowupTask`.
- Produces: `async def sync_note_followup(note: TreatmentNote, followup_question: str | None, created_by: uuid.UUID | None, db) -> None` — idempotent: cancels prior pending `next_visit_book` for (patient_id, doctor_id), and if the note is not final AND (`next_reporting_date` set OR `followup_question`), creates ONE pending `next_visit_book` task with `scheduled_date = visit_date + 1 day` and `what_to_ask = followup_question`.

- [ ] **Step 1: Failing test** — `tests/integration/test_treatment_enqueue.py`

```python
import uuid
from datetime import date
import pytest
from sqlalchemy import select
from backend.models.schema import Branch, Doctor, Patient, TreatmentNote, FollowupTask
from backend.services.treatment_followup import sync_note_followup


async def _seed(db):
    br = Branch(id=uuid.uuid4(), org_id=uuid.uuid4(), name="C", did_number="+910000000030")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000030")
    db.add_all([doc, pat]); await db.flush()
    return br, doc, pat


def _note(br, doc, pat, **kw):
    return TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                         visit_date=date(2026, 6, 22), **kw)


@pytest.mark.asyncio
async def test_enqueue_creates_next_visit_book(db):
    br, doc, pat = await _seed(db)
    n = _note(br, doc, pat, next_reporting_date=date(2026, 6, 25)); db.add(n); await db.flush()
    await sync_note_followup(n, followup_question="how is the pain?", created_by=None, db=db)
    tasks = (await db.execute(select(FollowupTask).where(FollowupTask.patient_id == pat.id))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].task_type == "next_visit_book"
    assert tasks[0].scheduled_date == date(2026, 6, 23)   # visit_date + 1
    assert tasks[0].what_to_ask == "how is the pain?"
    assert tasks[0].status == "pending" and tasks[0].channel == "voice"


@pytest.mark.asyncio
async def test_newer_note_cancels_prior_pending(db):
    br, doc, pat = await _seed(db)
    n1 = _note(br, doc, pat, next_reporting_date=date(2026, 6, 25)); db.add(n1); await db.flush()
    await sync_note_followup(n1, followup_question=None, created_by=None, db=db)
    n2 = _note(br, doc, pat, next_reporting_date=date(2026, 6, 28)); db.add(n2); await db.flush()
    await sync_note_followup(n2, followup_question=None, created_by=None, db=db)
    pend = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id, FollowupTask.status == "pending"))).scalars().all()
    assert len(pend) == 1   # only the latest survives


@pytest.mark.asyncio
async def test_final_note_cancels_and_does_not_enqueue(db):
    br, doc, pat = await _seed(db)
    n1 = _note(br, doc, pat, next_reporting_date=date(2026, 6, 25)); db.add(n1); await db.flush()
    await sync_note_followup(n1, followup_question=None, created_by=None, db=db)
    nf = _note(br, doc, pat, is_final=True); db.add(nf); await db.flush()
    await sync_note_followup(nf, followup_question=None, created_by=None, db=db)
    pend = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id, FollowupTask.status == "pending"))).scalars().all()
    assert pend == []
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** — `backend/services/treatment_followup.py`:

```python
"""Enqueue/cancel the next-visit follow-up call for a treatment note (M2).

Idempotent: at most one PENDING next_visit_book task per (patient, doctor). A
newer note supersedes the prior pending task; a final note cancels and enqueues
nothing. RULE 9: only operational fields ride the task — never steps_performed /
next_steps."""
from __future__ import annotations
import uuid
from datetime import timedelta
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.schema import TreatmentNote, FollowupTask


async def _cancel_pending(patient_id: uuid.UUID, doctor_id: uuid.UUID, db: AsyncSession) -> None:
    await db.execute(
        update(FollowupTask)
        .where(FollowupTask.patient_id == patient_id, FollowupTask.doctor_id == doctor_id,
               FollowupTask.task_type == "next_visit_book", FollowupTask.status == "pending")
        .values(status="completed")  # cancelled-superseded; not dialed
    )


async def sync_note_followup(note: TreatmentNote, followup_question: str | None,
                             created_by: uuid.UUID | None, db: AsyncSession) -> None:
    await _cancel_pending(note.patient_id, note.doctor_id, db)
    if note.is_final:
        await db.commit()
        return
    if not note.next_reporting_date and not followup_question:
        await db.commit()
        return
    db.add(FollowupTask(
        branch_id=note.branch_id, doctor_id=note.doctor_id, patient_id=note.patient_id,
        treatment_note_id=note.id, task_type="next_visit_book", channel="voice",
        what_to_ask=followup_question, scheduled_date=note.visit_date + timedelta(days=1),
        status="pending", created_by_user_id=created_by,
    ))
    await db.commit()
```

- [ ] **Step 4: Wire into the router** — in `backend/routers/treatment.py`, extend `NoteIn` with `followup_question: str | None = Field(None, max_length=2000)`, and at the M2 hook in `create_note` (and `edit_note`) after `db.refresh(note)`:

```python
    from backend.services.treatment_followup import sync_note_followup
    await sync_note_followup(note, body.followup_question,
                             uuid.UUID(user.user_id) if user.user_id else None, db)
```

- [ ] **Step 5: Run — expect PASS** `pytest tests/integration/test_treatment_enqueue.py -v`
- [ ] **Step 6: FIXLOG + full suite + commit** (`feat(treatment): idempotent next-visit follow-up enqueue`)

---

## Task 7: `/followups` thread endpoints (read + doctor reply)

**Files:**
- Modify: `backend/routers/treatment.py` (add 2 routes)
- Test: `tests/integration/test_followups_api.py`

**Interfaces:**
- Consumes: `FollowupTask`, `assert_branch_access`.
- Produces: `GET /patients/{patient_id}/followups?branch_id=` → ordered thread; `POST /patients/{patient_id}/followups` → creates a `doctor_advice` task (fires ASAP via the job).

- [ ] **Step 1: Failing test** — `tests/integration/test_followups_api.py`

```python
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from backend.main import app
from backend.models.schema import Branch, Doctor, Patient, FollowupTask
from backend.middleware.auth_middleware import get_current_user, CurrentUser


def _u(b, o): return CurrentUser(user_id=str(uuid.uuid4()), email="d@c", role="doctor",
                                 org_id=str(o), branch_ids=[str(b)], is_admin=False)


@pytest.mark.asyncio
async def test_doctor_reply_creates_advice_task(db):
    o = uuid.uuid4()
    br = Branch(id=uuid.uuid4(), org_id=o, name="C", did_number="+910000000040"); db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000040")
    db.add_all([doc, pat]); await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _u(br.id, o)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/followups", json={
                "branch_id": str(br.id), "doctor_id": str(doc.id),
                "message": "Take the prescribed painkiller twice daily."})
            assert r.status_code == 201, r.text
        task = (await db.execute(select(FollowupTask).where(FollowupTask.patient_id == pat.id))).scalar_one()
        assert task.task_type == "doctor_advice"
        assert task.what_to_ask == "Take the prescribed painkiller twice daily."
        assert task.status == "pending"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run — expect FAIL** (404)

- [ ] **Step 3: Implement** — add to `backend/routers/treatment.py`:

```python
from backend.models.schema import FollowupTask
from datetime import date as _date


class ReplyIn(BaseModel):
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    message: str = Field(..., min_length=1, max_length=2000)
    next_reporting_date: date | None = None
    treatment_note_id: uuid.UUID | None = None


@router.get("/patients/{patient_id}/followups")
async def list_followups(patient_id: uuid.UUID, branch_id: uuid.UUID,
                         user: CurrentUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await assert_branch_access(user, str(branch_id), db)
    rows = (await db.execute(
        select(FollowupTask).where(FollowupTask.patient_id == patient_id,
            FollowupTask.branch_id == branch_id,
            FollowupTask.task_type.in_(["next_visit_book", "doctor_advice"]))
        .order_by(FollowupTask.created_at.asc()))).scalars().all()
    return {"thread": [{"id": str(t.id), "task_type": t.task_type,
        "message": t.what_to_ask, "response": t.response_summary,
        "status": t.status, "scheduled_date": t.scheduled_date.isoformat() if t.scheduled_date else None,
        "created_at": t.created_at.isoformat()} for t in rows]}


@router.post("/patients/{patient_id}/followups", status_code=201)
async def doctor_reply(patient_id: uuid.UUID, body: ReplyIn,
                       user: CurrentUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    await assert_branch_access(user, str(body.branch_id), db)
    await _load_patient(patient_id, body.branch_id, db)
    t = FollowupTask(branch_id=body.branch_id, doctor_id=body.doctor_id, patient_id=patient_id,
        treatment_note_id=body.treatment_note_id, task_type="doctor_advice", channel="voice",
        what_to_ask=body.message, scheduled_date=_date.today(), status="pending",
        created_by_user_id=uuid.UUID(user.user_id) if user.user_id else None)
    db.add(t); await db.commit(); await db.refresh(t)
    return {"id": str(t.id), "task_type": t.task_type, "status": t.status}
```

- [ ] **Step 4: Run — expect PASS**; **Step 5: FIXLOG + full suite + commit** (`feat(treatment): follow-up thread read + doctor reply`)

---

## Task 8: `next_visit_followup_caller` job

**Files:**
- Create: `backend/jobs/next_visit_followup_caller.py`
- Modify: `backend/main.py` (register IntervalTrigger(minutes=15))
- Test: `tests/unit/test_next_visit_followup_caller.py`

**Interfaces:**
- Consumes: `FollowupTask`; existing dispatch pattern from `backend/jobs/pre_appt_reminder.py` (`create_dispatch`, `branch_outbound_trunk_id`).
- Produces: `async def run_next_visit_followups(now=None) -> int`; pure helper `_is_due(task, now_ist) -> bool`.

- [ ] **Step 1: Failing test** — `tests/unit/test_next_visit_followup_caller.py` (test the PURE due-logic, no network):

```python
from datetime import datetime, date
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from backend.jobs.next_visit_followup_caller import _is_due

IST = ZoneInfo("Asia/Kolkata")


def _task(tt, sched):
    return SimpleNamespace(task_type=tt, scheduled_date=sched, attempt_count=0, status="pending")


def test_next_visit_book_due_after_9am():
    assert _is_due(_task("next_visit_book", date(2026, 6, 23)), datetime(2026, 6, 23, 9, 5, tzinfo=IST)) is True

def test_next_visit_book_not_due_before_9am():
    assert _is_due(_task("next_visit_book", date(2026, 6, 23)), datetime(2026, 6, 23, 8, 0, tzinfo=IST)) is False

def test_doctor_advice_due_within_hours():
    assert _is_due(_task("doctor_advice", date(2026, 6, 23)), datetime(2026, 6, 23, 14, 0, tzinfo=IST)) is True

def test_nothing_due_at_night():
    now = datetime(2026, 6, 23, 22, 0, tzinfo=IST)
    assert _is_due(_task("doctor_advice", date(2026, 6, 23)), now) is False
    assert _is_due(_task("next_visit_book", date(2026, 6, 23)), now) is False

def test_future_scheduled_not_due():
    assert _is_due(_task("next_visit_book", date(2026, 6, 25)), datetime(2026, 6, 23, 10, 0, tzinfo=IST)) is False
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement** — `backend/jobs/next_visit_followup_caller.py`:

```python
"""Dispatch outbound treatment follow-up calls (M2).

Every 15 min. Calling hours 09:00-20:00 branch-local IST (DPDP courtesy, RULE 8).
next_visit_book fires at/after 09:00 on its scheduled day; doctor_advice fires
ASAP. RULE 9: metadata carries ONLY operational fields + the doctor's message
(what_to_ask) — never steps_performed/next_steps. Reuses the reminder dispatch."""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import structlog
from sqlalchemy import select
from backend.database import AsyncSessionLocal
from backend.models.schema import FollowupTask, Branch, Doctor, Patient, TreatmentNote
from backend.services.telephony import branch_outbound_trunk_id

logger = structlog.get_logger()
IST = ZoneInfo("Asia/Kolkata")
CALL_START_H, CALL_END_H = 9, 20
AGENT_NAME = "vachanam-agent"


def _is_due(task, now_ist: datetime) -> bool:
    if not (CALL_START_H <= now_ist.hour < CALL_END_H):
        return False
    sched = task.scheduled_date or now_ist.date()
    if sched > now_ist.date():
        return False
    return task.task_type in ("next_visit_book", "doctor_advice")


async def _dispatch(task, branch, doctor, patient, target_date) -> None:
    from livekit import api as lk_api
    lkapi = lk_api.LiveKitAPI()
    try:
        meta = {"call_type": task.task_type, "branch_id": str(branch.id),
                "outbound_trunk_id": branch_outbound_trunk_id(branch),
                "phone_number": patient.phone, "task_id": str(task.id),
                "patient_name": patient.name, "doctor_name": doctor.name,
                "doctor_id": str(doctor.id), "message": task.what_to_ask or ""}
        if target_date:
            meta["target_date"] = target_date
            meta["window"] = 2
        await lkapi.agent_dispatch.create_dispatch(lk_api.CreateAgentDispatchRequest(
            agent_name=AGENT_NAME, room=f"followup-{uuid.uuid4().hex[:10]}",
            metadata=json.dumps(meta)))
        logger.info("followup_call_dispatched", task_id=str(task.id),
                    call_type=task.task_type, phone_last4=(patient.phone or "")[-4:])
    finally:
        await lkapi.aclose()


async def run_next_visit_followups(now: datetime | None = None) -> int:
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    if not (CALL_START_H <= now_ist.hour < CALL_END_H):
        return 0
    dispatched = 0
    async with AsyncSessionLocal() as db:
        tasks = (await db.execute(select(FollowupTask).where(
            FollowupTask.status == "pending", FollowupTask.channel == "voice",
            FollowupTask.task_type.in_(["next_visit_book", "doctor_advice"])))).scalars().all()
        for t in tasks:
            if not _is_due(t, now_ist):
                continue
            branch = (await db.execute(select(Branch).where(Branch.id == t.branch_id))).scalar_one_or_none()
            doctor = (await db.execute(select(Doctor).where(Doctor.id == t.doctor_id))).scalar_one_or_none()
            patient = (await db.execute(select(Patient).where(Patient.id == t.patient_id))).scalar_one_or_none()
            if not (branch and doctor and patient and patient.phone):
                t.status = "unreachable"
                logger.warning("followup_skipped_missing_data", task_id=str(t.id))
                continue
            target_date = None
            if t.treatment_note_id:
                tn = (await db.execute(select(TreatmentNote).where(
                    TreatmentNote.id == t.treatment_note_id))).scalar_one_or_none()
                if tn and tn.is_final:
                    t.status = "completed"   # treatment closed since enqueue
                    continue
                if tn and tn.next_reporting_date:
                    target_date = tn.next_reporting_date.isoformat()
            t.attempt_count = (t.attempt_count or 0) + 1
            t.status = "in_progress"
            try:
                await _dispatch(t, branch, doctor, patient, target_date)
                dispatched += 1
            except Exception as e:  # noqa: BLE001
                logger.error("followup_dispatch_failed", task_id=str(t.id), error=str(e)[:160])
                t.status = "unreachable" if t.attempt_count >= (t.max_attempts or 3) else "pending"
        await db.commit()
    return dispatched
```

- [ ] **Step 4: Register the job** — `backend/main.py` (next to the other `scheduler.add_job` calls):

```python
from backend.jobs.next_visit_followup_caller import run_next_visit_followups
scheduler.add_job(run_next_visit_followups, IntervalTrigger(minutes=15),
                  id="next_visit_followups", replace_existing=True)
```

- [ ] **Step 5: Run — expect PASS** `pytest tests/unit/test_next_visit_followup_caller.py -v`
- [ ] **Step 6: FIXLOG + full suite + commit** (`feat(treatment): 9am/ASAP follow-up caller job`)

---

## Task 9: agent — `next_visit_book` + `doctor_advice` flows + write-back

**Files:**
- Modify: `agent/livekit_minimal/agent.py` (2 prompt extras; handle the 2 `call_type`s; write `response_summary` on shutdown)
- Test: `tests/unit/test_agent_followup_metadata.py`

**Interfaces:**
- Consumes: dispatch metadata `{call_type, message, target_date?, window?, task_id, patient_name, doctor_name}`.
- Produces: `NEXT_VISIT_PROMPT_EXTRA`, `DOCTOR_ADVICE_PROMPT_EXTRA`, `_FOLLOWUP_CALLTYPES`, `_followup_meta_safe(meta) -> dict`.

- [ ] **Step 1: Failing test** — `tests/unit/test_agent_followup_metadata.py`

```python
import agent.livekit_minimal.agent as ag


def test_prompt_extras_relay_only_and_promise_doctor():
    assert "relay" in ag.DOCTOR_ADVICE_PROMPT_EXTRA.lower()
    assert "{message}" in ag.DOCTOR_ADVICE_PROMPT_EXTRA
    assert "inform the doctor" in ag.NEXT_VISIT_PROMPT_EXTRA.lower()
    assert "{message}" in ag.NEXT_VISIT_PROMPT_EXTRA


def test_followup_metadata_helper_excludes_private_notes():
    meta = {"call_type": "next_visit_book", "message": "how is pain?",
            "patient_name": "P", "doctor_name": "D", "target_date": "2026-06-25",
            "steps_performed": "LEAK", "next_steps": "LEAK"}
    safe = ag._followup_meta_safe(meta)
    assert "steps_performed" not in safe and "next_steps" not in safe
    assert safe["message"] == "how is pain?"
```

- [ ] **Step 2: Run — expect FAIL** (attrs missing)

- [ ] **Step 3: Implement** — in `agent/livekit_minimal/agent.py`:

(a) Add near `REMINDER_PROMPT_EXTRA` (~line 239):

```python
NEXT_VISIT_PROMPT_EXTRA = (
    "\n\nTHIS IS A TREATMENT FOLLOW-UP CALL. You already know this patient — never "
    "ask who they are or restart the new-patient flow.\n"
    "1) If a message is given, ask it warmly in the clinic's language: \"{message}\".\n"
    "2) If a target date is given ({target_date}), offer to book a visit within 2 "
    "days of it; on agreement use the booking tools (assign a token around that "
    "date) and confirm in one breath.\n"
    "3) You are a MESSENGER, not a doctor: give NO medical advice, NO diagnosis, NO "
    "triage. If the patient reports ANY problem or pain, say warmly: 'I will inform "
    "the doctor and they will get back to you as soon as possible.' Do not advise.\n"
    "Keep every reply to two short sentences."
)

DOCTOR_ADVICE_PROMPT_EXTRA = (
    "\n\nTHIS IS A DOCTOR-ADVICE RELAY CALL. The doctor reviewed the patient's "
    "concern and wrote a message. RELAY it warmly and faithfully in the clinic's "
    "language — do NOT add, interpret, or invent any medical content of your own "
    "(RULE 7). The doctor's message: \"{message}\".\n"
    "After relaying, ask if they have more concerns; if a target date "
    "({target_date}) is given, offer to book within 2 days of it. If they report a "
    "new problem, say 'I will inform the doctor and get back to you as soon as "
    "possible.' Two short sentences per reply."
)

_FOLLOWUP_CALLTYPES = {"next_visit_book", "doctor_advice"}


def _followup_meta_safe(meta: dict) -> dict:
    """RULE 9: the ONLY metadata fields allowed to reach the LLM/agent for a
    follow-up call. Private clinical notes (steps_performed/next_steps) must never
    appear here even if a future caller accidentally includes them."""
    allowed = ("call_type", "message", "target_date", "window",
               "patient_name", "doctor_name", "doctor_id", "task_id")
    return {k: meta[k] for k in allowed if k in meta}
```

(b) Where `is_reminder`/`is_rebook_call` are derived, add `is_followup = meta.get("call_type") in _FOLLOWUP_CALLTYPES` and treat it on the outbound path (welcome bridge + clinic language, like reminders).

(c) When building `instructions`:

```python
    if meta.get("call_type") == "next_visit_book":
        instructions += NEXT_VISIT_PROMPT_EXTRA.format(
            message=meta.get("message", ""), target_date=meta.get("target_date", ""))
    elif meta.get("call_type") == "doctor_advice":
        instructions += DOCTOR_ADVICE_PROMPT_EXTRA.format(
            message=meta.get("message", ""), target_date=meta.get("target_date", ""))
```

(d) In `_cleanup_on_shutdown`, if `meta.get("task_id")`: write the patient's captured reply (derive from the transcript/last user turns already collected for CallQuality) to `FollowupTask.response_summary` and set `status="completed"` (own short-lived session, never the live call's `db`; best-effort, must not break teardown). The dashboard thread (Task 7 GET) reads `response_summary` — no extra column needed.

(e) **Opening greeting** — the post-`session.start()` greeting block currently branches `is_reminder` / `is_rebook_call` / `else` (inbound disclosure). A follow-up call is outbound but is NEITHER, so it must NOT fall through to the inbound disclosure. Add a branch BEFORE the `else`: for `is_followup`, speak a short by-name greeting (e.g. `lines.known_caller_greeting.format(patient=meta.get("patient_name",""), clinic=branch_name)`) so the agent opens warmly and the prompt extra drives the rest. Confirm the welcome bridge already fires (the clip block is unconditional on `branch_name`, so it does).

- [ ] **Step 4: Run — expect PASS** `pytest tests/unit/test_agent_followup_metadata.py -v`
- [ ] **Step 5: FIXLOG + full suite + commit** (`feat(agent): treatment follow-up + doctor-advice relay flows`)

> **Live proof (manual, like FIXLOG #146):** dispatch one `next_visit_book` and one `doctor_advice` test call (adapt `scripts/_fire_test_reminder.py` for the new call_types); confirm the agent asks/relays the message, books ±2 days, never advises, and `response_summary` is written. Record room ids + a log excerpt in the FIXLOG row.

---

## Task 10: retention — wipe treatment notes + thread health text

**Files:**
- Modify: `backend/jobs/data_retention.py`
- Test: `tests/unit/test_data_retention_treatment.py`

- [ ] **Step 1: Failing test** — `tests/unit/test_data_retention_treatment.py`

```python
import uuid
from datetime import date, datetime, timezone, timedelta
import pytest
from sqlalchemy import select
from backend.models.schema import Branch, Doctor, Patient, TreatmentNote, FollowupTask
from backend.jobs.data_retention import run_data_retention
from backend.config import settings


@pytest.mark.asyncio
async def test_anonymise_wipes_treatment_notes_and_thread_text(db):
    old = datetime.now(timezone.utc) - timedelta(days=settings.data_retention_days + 5)
    br = Branch(id=uuid.uuid4(), org_id=uuid.uuid4(), name="C", did_number="+910000000050")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000050", created_at=old)
    db.add_all([doc, pat]); await db.flush()
    n = TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                      visit_date=date(2026,1,1), steps_performed="root canal")
    db.add(n); await db.flush()
    t = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                     task_type="doctor_advice", channel="voice",
                     what_to_ask="advice", response_summary="still pain", treatment_note_id=n.id)
    db.add(t); await db.commit()

    await run_data_retention()

    notes = (await db.execute(select(TreatmentNote).where(TreatmentNote.patient_id == pat.id))).scalars().all()
    assert notes == []  # notes deleted on anonymise
    ft = (await db.execute(select(FollowupTask).where(FollowupTask.patient_id == pat.id))).scalar_one()
    assert ft.what_to_ask is None and ft.response_summary is None  # health text wiped
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement** — inside the `for p in stale:` loop in `backend/jobs/data_retention.py`, after `p.anonymized_at = now`:

```python
            # Treatment health-data erasure (RULE 9): delete the patient's
            # treatment notes outright and NULL the health text on their follow-up
            # thread (keep the task rows for non-PII outcome trends).
            from backend.models.schema import TreatmentNote as _TN, FollowupTask as _FT
            await db.execute(_TN.__table__.delete().where(_TN.patient_id == p.id))
            await db.execute(_FT.__table__.update().where(_FT.patient_id == p.id)
                             .values(what_to_ask=None, response_summary=None))
```

(Note: `treatment_notes.token_id` → tokens is RESTRICT and FollowupTask → treatment_notes is RESTRICT; delete `treatment_notes` only AFTER nulling/handling any FollowupTask.treatment_note_id that would block it — if RESTRICT blocks the delete, first run `_FT.__table__.update().where(_FT.patient_id==p.id).values(treatment_note_id=None, what_to_ask=None, response_summary=None)` then delete the notes.)

- [ ] **Step 4: Run — expect PASS**; **Step 5: FIXLOG + full suite + commit** (`feat(treatment): retention wipes treatment notes + thread text`)

---

## Task 11: PWA — follow-up thread + reply UI + needs-attention

**Files:**
- Modify: `frontend/src/pages/Treatments.jsx`, `frontend/src/api/treatment.js`
- Test: manual + `npm run build`

- [ ] **Step 1: API** — append to `frontend/src/api/treatment.js`:

```javascript
export const listFollowups = (patientId, branchId) =>
  api.get(`/treatment/patients/${patientId}/followups`, { params: { branch_id: branchId } })
     .then((r) => r.data.thread);

export const replyToPatient = (patientId, payload) =>
  api.post(`/treatment/patients/${patientId}/followups`, payload).then((r) => r.data);
```

- [ ] **Step 2: UI** — in `Treatments.jsx`, under the timeline add a thread panel: each `{task_type, message, response, status}` as a chat-style row (clinic message vs patient reply); a **"Reply to patient"** textarea + send (POST `replyToPatient` with `branch_id`, `doctor_id`, `message`); a **"needs attention"** badge when any thread item has a `response` not yet acknowledged or `status === "unreachable"`. Invalidate the followups query on send.

- [ ] **Step 3: Proof** — `cd frontend && npm run build` succeeds; manual: doctor sees a captured reply, types advice, send → a `doctor_advice` row appears `pending`. Screenshot in PR.

- [ ] **Step 4: FIXLOG (⚠ manual UI) + commit** (`feat(treatment): follow-up thread + reply UI`)

---

## Final review (after all tasks)

- [ ] `pytest tests/ -q` — green except the known pre-existing env failures (7 DB-fixture errors with no local Postgres + 1 live-smallest 500). On CI (Docker Postgres) ALL new tests pass.
- [ ] Re-read the spec; confirm every section maps to a shipped task.
- [ ] One end-to-end live proof: doctor logs a visit with a question + next date → next-morning call asks + books ±2 days + captures a reported problem → doctor replies in dashboard → relay call delivers the advice. Record in FIXLOG.
- [ ] Use superpowers:finishing-a-development-branch.
