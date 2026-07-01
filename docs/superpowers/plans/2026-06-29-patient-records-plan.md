# Patient Records: Dedup + Patient Information View + Greet-by-Name — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De-duplicate patient records (one primary owner per phone + distinct family members), add an editable Patient Information view, and have the agent greet recognized callers by name and book efficiently (self vs. someone-else).

**Architecture:** A partial unique index `(branch_id, phone, lower(name))` enforces no-duplicate at the DB. A one-time additive migration merges existing duplicates (repointing FK rows) and backfills an `is_primary` owner per phone; the merge SQL lives in one reusable module so the migration and its test share a single source. Find-or-create in both booking paths (voice agent + walk-in desk) already matches case-insensitively — the only change is setting `is_primary` on creation. A new branch-scoped `patients` router serves the list/edit view. The agent recognizes the primary by name and the known-caller prompt-extra drives the self/other booking split.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Alembic (Postgres), Neon Postgres, React 18 + Vite + TanStack Query, LiveKit voice agent (Python).

## Global Constraints

- RULE 1 tenant isolation: every query/route branch-scoped (`assert_branch_access`); super_admin denied on clinic-PII routes (`forbid_admin`).
- RULE 9 PII discipline: name/age/phone are PII — patient-info routes clinic-only; no PII in logs.
- Telugu agent lines are English directives in the prompt rendered by the LLM in the caller's language — never hand-write Telugu strings in code.
- Additive Alembic migration forward from head `x21welcomeshort2026`; new revision id `y22patientdedup2026`.
- Dedup rule: within a branch, no two patients share the same phone AND `lower(name)`. A phone may have MULTIPLE patients (family) with DISTINCT names. Exactly one patient per phone is `is_primary` (the owner). NULL-phone rows: each is its own primary.
- Proof for every change: a failing test that then passes. FIXLOG row per task. Full suite re-run (Docker Postgres+Redis up).
- Known pre-existing failures to ignore: `test_smallest_voice` (live 500); `test_confirm_booking_transient_calendar_failure_single_row` (FIXLOG #23, env tenacity/Py3.14).

---

## File Structure

- `backend/models/schema.py` — add `Patient.is_primary` + partial unique index in `__table_args__`.
- `backend/services/patient_dedup.py` (new) — `MERGE_SQL` + `BACKFILL_PRIMARY_SQL` (lists of SQL text): the single source of the merge/backfill statements, shared by migration and test.
- `alembic/versions/y22patientdedup2026_patient_dedup.py` (new) — add column → run merge → run backfill → create index.
- `agent/tools/booking_tools.py` — set `is_primary` on patient creation in `confirm_booking`; `recognize_caller_name` returns the primary's name.
- `backend/routers/queue.py` — set `is_primary` on walk-in patient creation.
- `backend/routers/patients.py` (new) — GET list (with last doctor) + PATCH edit (409 on collision).
- `backend/main.py` — register the patients router.
- `frontend/src/api/patients.js` (new) — list + patch client.
- `frontend/src/pages/Patients.jsx` (new) — Patient Information table + inline edit.
- `frontend/src/App.jsx` + `frontend/src/components/Shell.jsx` — route + nav entry.
- `agent/livekit_minimal/agent.py` — known-caller booking prompt-extra (self/other split), extracted to a testable constant.

---

## Task 1: Patient.is_primary column + partial unique index

**Files:**
- Modify: `backend/models/schema.py:210-232` (Patient model)
- Test: `tests/unit/test_patient_dedup_model.py` (new)

**Interfaces:**
- Produces: `Patient.is_primary` (bool, default False, NOT NULL); index name `uq_patient_branch_phone_name` present in `Patient.__table__.indexes`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_patient_dedup_model.py`:

```python
from backend.models.schema import Patient


def test_patient_has_is_primary_column():
    col = Patient.__table__.columns["is_primary"]
    assert col.nullable is False


def test_patient_has_partial_unique_index():
    idx = {i.name: i for i in Patient.__table__.indexes}
    assert "uq_patient_branch_phone_name" in idx
    target = idx["uq_patient_branch_phone_name"]
    assert target.unique is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_patient_dedup_model.py -v`
Expected: FAIL — `KeyError: 'is_primary'`.

- [ ] **Step 3: Add the column + index**

In `backend/models/schema.py`, confirm the top-of-file imports include `Index`, `func`, and `text` (from `sqlalchemy`). Add them to the existing sqlalchemy import if missing.

Inside `class Patient(Base)`, add the column after `followup_consent` (line ~223):

```python
    # Exactly one patient per phone is the owner (is_primary). Family members
    # sharing the phone are is_primary=False. NULL-phone rows: each its own primary.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

At the END of the `Patient` class body (after the relationships), add:

```python
    __table_args__ = (
        # No two patients per branch share the same phone AND name (case-
        # insensitive). Partial: only enforced when a phone is present, so
        # several NULL-phone walk-ins never collide. Family members = distinct
        # names on the same phone, so they pass.
        Index(
            "uq_patient_branch_phone_name",
            "branch_id",
            "phone",
            func.lower(name),
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
    )
```

Note: `func.lower(name)` references the `name` Mapped column defined above in the same class body.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_patient_dedup_model.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/models/schema.py tests/unit/test_patient_dedup_model.py
git commit -m "feat(schema): Patient.is_primary + partial unique (branch,phone,lower-name) index"
```

---

## Task 2: Merge + backfill SQL module (shared by migration and test)

**Files:**
- Create: `backend/services/patient_dedup.py`
- Test: `tests/integration/test_patient_dedup_merge.py` (new)

**Interfaces:**
- Produces: `MERGE_SQL: list[str]` (repoints tokens/treatment_notes/followup_tasks from duplicate patients to the earliest-created canonical, then deletes duplicates); `BACKFILL_PRIMARY_SQL: list[str]` (sets `is_primary=TRUE` for the owner per phone and for every NULL-phone row). Both are plain Postgres SQL strings, executed in list order.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patient_dedup_merge.py`:

```python
import uuid
import pytest
from sqlalchemy import text, select

from backend.models.schema import Branch, Doctor, Patient, Token, Organization
from backend.services.patient_dedup import MERGE_SQL, BACKFILL_PRIMARY_SQL


async def _branch(db):
    org = Organization(id=uuid.uuid4(), name="Org", plan="clinic")
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="Br", timezone="Asia/Kolkata")
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr", specialization="dental",
                 booking_type="token", status="active")
    db.add_all([org, br, doc])
    await db.flush()
    return br, doc


@pytest.mark.asyncio
async def test_merge_repoints_and_dedups(db):
    br, doc = await _branch(db)
    # Two rows, same phone, same name different case -> duplicates.
    canonical = Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone="+919000000001")
    dup = Patient(id=uuid.uuid4(), branch_id=br.id, name="ravi", phone="+919000000001")
    db.add_all([canonical, dup])
    await db.flush()
    # created_at ordering: canonical first. Force it deterministically.
    await db.execute(text("UPDATE patients SET created_at = now() - interval '1 hour' WHERE id = :i"),
                     {"i": str(canonical.id)})
    tok = Token(id=uuid.uuid4(), branch_id=br.id, doctor_id=doc.id, patient_id=dup.id,
                date=__import__("datetime").date.today(), token_number=1, status="confirmed",
                source="voice")
    db.add(tok)
    await db.flush()

    # The live unique index would block seeding dups — drop it, run merge, recreate.
    await db.execute(text("DROP INDEX IF EXISTS uq_patient_branch_phone_name"))
    for stmt in MERGE_SQL:
        await db.execute(text(stmt))
    await db.flush()

    remaining = (await db.execute(select(Patient).where(Patient.branch_id == br.id))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].id == canonical.id
    moved = (await db.execute(select(Token).where(Token.id == tok.id))).scalar_one()
    assert moved.patient_id == canonical.id


@pytest.mark.asyncio
async def test_backfill_sets_one_primary_per_phone(db):
    br, doc = await _branch(db)
    a = Patient(id=uuid.uuid4(), branch_id=br.id, name="Amma", phone="+919000000002")
    b = Patient(id=uuid.uuid4(), branch_id=br.id, name="Nanna", phone="+919000000002")
    c = Patient(id=uuid.uuid4(), branch_id=br.id, name="Walkin", phone=None)
    db.add_all([a, b, c])
    await db.flush()
    await db.execute(text("UPDATE patients SET created_at = now() - interval '1 hour' WHERE id = :i"),
                     {"i": str(a.id)})
    for stmt in BACKFILL_PRIMARY_SQL:
        await db.execute(text(stmt))
    await db.flush()
    rows = {p.id: p for p in (await db.execute(
        select(Patient).where(Patient.branch_id == br.id))).scalars().all()}
    assert rows[a.id].is_primary is True     # earliest on the shared phone
    assert rows[b.id].is_primary is False
    assert rows[c.id].is_primary is True     # NULL-phone -> own primary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_patient_dedup_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.services.patient_dedup`.

- [ ] **Step 3: Write the module**

Create `backend/services/patient_dedup.py`:

```python
"""One-time patient de-duplication SQL, shared by the y22 migration and its test.

Postgres-only. MERGE_SQL repoints child rows (tokens, treatment_notes,
followup_tasks) from duplicate patients to the earliest-created canonical row
per (branch_id, phone, lower(name)), then deletes the duplicates.
BACKFILL_PRIMARY_SQL marks exactly one is_primary owner per phone (earliest
created_at) and every NULL-phone row as its own primary.

Statements run in list order. Idempotent enough to re-run: after a merge there
are no duplicates left, so the repoint/delete become no-ops.
"""

# ponytail: raw SQL, not ORM — this is a bulk one-time cleanup; window functions
# do it in one pass per table instead of N per-row loads.

_RANK = """
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY branch_id, phone, lower(name)
               ORDER BY created_at ASC, id ASC
           ) AS canonical_id
    FROM patients
    WHERE phone IS NOT NULL
)
"""

MERGE_SQL: list[str] = [
    _RANK + """
    UPDATE tokens t SET patient_id = r.canonical_id
    FROM ranked r
    WHERE t.patient_id = r.id AND r.id <> r.canonical_id;
    """,
    _RANK + """
    UPDATE treatment_notes tn SET patient_id = r.canonical_id
    FROM ranked r
    WHERE tn.patient_id = r.id AND r.id <> r.canonical_id;
    """,
    _RANK + """
    UPDATE followup_tasks ft SET patient_id = r.canonical_id
    FROM ranked r
    WHERE ft.patient_id = r.id AND r.id <> r.canonical_id;
    """,
    _RANK + """
    DELETE FROM patients p
    USING ranked r
    WHERE p.id = r.id AND r.id <> r.canonical_id;
    """,
]

BACKFILL_PRIMARY_SQL: list[str] = [
    "UPDATE patients SET is_primary = TRUE WHERE phone IS NULL;",
    """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY branch_id, phone
                   ORDER BY created_at ASC, id ASC
               ) AS primary_id
        FROM patients
        WHERE phone IS NOT NULL
    )
    UPDATE patients p SET is_primary = TRUE
    FROM ranked r
    WHERE p.id = r.id AND r.id = r.primary_id;
    """,
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_patient_dedup_merge.py -v`
Expected: PASS (2 passed). If your `db` fixture keeps the unique index (create_all builds it from Task 1's schema), the DROP INDEX in the first test handles it; the second test seeds distinct names so it never needs the drop.

- [ ] **Step 5: Commit**

```bash
git add backend/services/patient_dedup.py tests/integration/test_patient_dedup_merge.py
git commit -m "feat(dedup): shared merge + is_primary backfill SQL with tests"
```

---

## Task 3: Alembic migration y22 (column + merge + backfill + index)

**Files:**
- Create: `alembic/versions/y22patientdedup2026_patient_dedup.py`
- Test: `tests/unit/test_migration_y22_head.py` (new)

**Interfaces:**
- Consumes: `backend.services.patient_dedup.MERGE_SQL`, `BACKFILL_PRIMARY_SQL`.
- Produces: revision `y22patientdedup2026`, `down_revision = "x21welcomeshort2026"`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_y22_head.py`:

```python
from pathlib import Path


def test_y22_is_head_after_x21():
    src = Path("alembic/versions/y22patientdedup2026_patient_dedup.py").read_text(encoding="utf-8")
    assert 'revision = "y22patientdedup2026"' in src
    assert 'down_revision = "x21welcomeshort2026"' in src


def test_no_other_migration_points_past_x21():
    # y22 must be the new single head — nothing else may claim x21 as parent.
    versions = Path("alembic/versions")
    claimants = [
        f.name for f in versions.glob("*.py")
        if 'down_revision = "x21welcomeshort2026"' in f.read_text(encoding="utf-8")
    ]
    assert claimants == ["y22patientdedup2026_patient_dedup.py"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_migration_y22_head.py -v`
Expected: FAIL — file does not exist (`FileNotFoundError`).

- [ ] **Step 3: Write the migration**

Create `alembic/versions/y22patientdedup2026_patient_dedup.py`:

```python
"""Patient de-duplication: is_primary column, merge existing duplicates, and a
partial unique index on (branch_id, phone, lower(name)).

Additive + one-time data cleanup. Upgrade order: add column -> merge duplicate
patients (repoint tokens/treatment_notes/followup_tasks, delete dups) ->
backfill is_primary (one owner per phone; NULL-phone rows own primary) ->
create the partial unique index (safe now that duplicates are gone).

downgrade() drops the index + column only — the merge is NOT reversed
(irreversible data cleanup).

Revision ID: y22patientdedup2026
Revises: x21welcomeshort2026
Create Date: 2026-06-29
"""
import sqlalchemy as sa
from alembic import op

from backend.services.patient_dedup import MERGE_SQL, BACKFILL_PRIMARY_SQL

revision = "y22patientdedup2026"
down_revision = "x21welcomeshort2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for stmt in MERGE_SQL:
        op.execute(stmt)
    for stmt in BACKFILL_PRIMARY_SQL:
        op.execute(stmt)
    op.create_index(
        "uq_patient_branch_phone_name",
        "patients",
        ["branch_id", "phone", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_patient_branch_phone_name", table_name="patients")
    op.drop_column("patients", "is_primary")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_migration_y22_head.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/y22patientdedup2026_patient_dedup.py tests/unit/test_migration_y22_head.py
git commit -m "feat(migration): y22 patient dedup — is_primary + merge + partial unique index"
```

---

## Task 4: Set is_primary on patient creation (voice agent + walk-in desk)

**Files:**
- Modify: `agent/tools/booking_tools.py:770-778` (confirm_booking create branch)
- Modify: `backend/routers/queue.py:421-470` (walk-in create branch)
- Test: `tests/integration/test_patient_is_primary_on_create.py` (new)

**Interfaces:**
- Consumes: `Patient.is_primary` (Task 1).
- Note: the phone+name match in BOTH paths is ALREADY case-insensitive (`p.name.strip().lower() == wanted`). No match-logic change needed — only set `is_primary` on the create path.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patient_is_primary_on_create.py`:

```python
import uuid
import datetime
import pytest
from sqlalchemy import select

from backend.models.schema import Branch, Doctor, Patient, Organization
from agent.tools.booking_tools import confirm_booking


async def _setup(db):
    org = Organization(id=uuid.uuid4(), name="Org", plan="clinic")
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="Br", timezone="Asia/Kolkata")
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr", specialization="dental",
                 booking_type="token", status="active")
    db.add_all([org, br, doc])
    await db.flush()
    return br, doc


@pytest.mark.asyncio
async def test_first_patient_on_phone_is_primary(db):
    br, doc = await _setup(db)
    res = await confirm_booking(
        branch_id=br.id, doctor_id=doc.id, patient_name="Ravi",
        patient_phone="+919000000010", patient_age=30,
        booking_date=datetime.date.today(), db=db,
    )
    assert res["success"] is True
    p = (await db.execute(select(Patient).where(
        Patient.phone == "+919000000010", Patient.branch_id == br.id))).scalar_one()
    assert p.is_primary is True


@pytest.mark.asyncio
async def test_family_member_is_not_primary(db):
    br, doc = await _setup(db)
    await confirm_booking(branch_id=br.id, doctor_id=doc.id, patient_name="Ravi",
                          patient_phone="+919000000011", patient_age=30,
                          booking_date=datetime.date.today(), db=db)
    await confirm_booking(branch_id=br.id, doctor_id=doc.id, patient_name="Sita",
                          patient_phone="+919000000011", patient_age=28,
                          booking_date=datetime.date.today(), db=db, different_person=True)
    rows = {p.name: p for p in (await db.execute(select(Patient).where(
        Patient.phone == "+919000000011", Patient.branch_id == br.id))).scalars().all()}
    assert rows["Ravi"].is_primary is True
    assert rows["Sita"].is_primary is False
```

Note: match `confirm_booking`'s real signature (see `agent/tools/booking_tools.py` around line 700 for parameter names/order); adjust keyword args if they differ. If a Redis-backed token assign is required, reuse the fixture pattern from `tests/integration/test_booking_flow.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_patient_is_primary_on_create.py -v`
Expected: FAIL — `is_primary` is False (default) for the first patient.

- [ ] **Step 3: Set is_primary in the agent path**

In `agent/tools/booking_tools.py`, the create branch begins at line 770. `same_phone` (line 753) already holds every patient on that phone. Change the `Patient(...)` construction to:

```python
        patient = Patient(
            branch_id=branch_id,
            name=patient_name,
            phone=patient_phone,
            age=patient_age,
            gender=patient_gender,
            followup_consent=followup_consent,
            # First patient on this phone owns it; family members added later are not.
            is_primary=(len(same_phone) == 0),
        )
```

- [ ] **Step 4: Set is_primary in the walk-in path**

In `backend/routers/queue.py`, the create branch is at line 465. `same_phone` is only assigned when `norm_phone` is truthy (line 422); a NULL-phone walk-in has no `same_phone` in scope. Change the create to:

```python
        if patient is None:
            # First patient on this phone owns it (is_primary). A NULL-phone
            # walk-in has no phone-mates, so it is its own primary too.
            existing_on_phone = same_phone if norm_phone else []
            patient = Patient(
                branch_id=branch_uuid,
                name=body.patient_name,
                phone=norm_phone,
                is_primary=(len(existing_on_phone) == 0),
            )
            db.add(patient)
            await db.flush()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/integration/test_patient_is_primary_on_create.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/tools/booking_tools.py backend/routers/queue.py tests/integration/test_patient_is_primary_on_create.py
git commit -m "feat(booking): set Patient.is_primary on first-per-phone create (agent + desk)"
```

---

## Task 5: Patients router — GET list (last doctor) + PATCH edit (409 on collision)

**Files:**
- Create: `backend/routers/patients.py`
- Modify: `backend/main.py:248-260` (register router)
- Test: `tests/integration/test_patients_router.py` (new)

**Interfaces:**
- Produces:
  - `GET /patients/branches/{branch_id}/patients` → `{"patients": [{"id","name","age","phone","is_primary","last_doctor"}]}` sorted by name; `last_doctor` = doctor name on the patient's most-recent Token (by `date` desc, then `created_at` desc), else `null`.
  - `PATCH /patients/{patient_id}` body `{"branch_id", "name"?, "age"?, "phone"?}` → 200 `{"id","name","age","phone","is_primary"}`; 404 if not in branch; 409 `{"detail":"duplicate_patient"}` if the new (phone, lower(name)) collides with another patient; 403 for super_admin (via `forbid_admin`).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patients_router.py` (follow the auth/fixture pattern in `tests/integration/test_treatment_notes_api.py` for building `client`, an org_admin token, and a branch):

```python
import uuid
import datetime
import pytest
from sqlalchemy import select

from backend.models.schema import Patient, Token, Doctor


@pytest.mark.asyncio
async def test_list_returns_last_doctor(client, org_admin_headers, branch, doctor, db):
    p = Patient(id=uuid.uuid4(), branch_id=branch.id, name="Ravi",
                phone="+919000000020", age=30, is_primary=True)
    db.add(p)
    await db.flush()
    db.add(Token(id=uuid.uuid4(), branch_id=branch.id, doctor_id=doctor.id,
                 patient_id=p.id, date=datetime.date.today(), token_number=1,
                 status="confirmed", source="voice"))
    await db.commit()
    r = await client.get(f"/patients/branches/{branch.id}/patients", headers=org_admin_headers)
    assert r.status_code == 200
    row = next(x for x in r.json()["patients"] if x["id"] == str(p.id))
    assert row["last_doctor"] == doctor.name


@pytest.mark.asyncio
async def test_patch_edits_name_age(client, org_admin_headers, branch, db):
    p = Patient(id=uuid.uuid4(), branch_id=branch.id, name="Old",
                phone="+919000000021", age=20, is_primary=True)
    db.add(p); await db.commit()
    r = await client.patch(f"/patients/{p.id}",
                           json={"branch_id": str(branch.id), "name": "New", "age": 21},
                           headers=org_admin_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "New" and r.json()["age"] == 21


@pytest.mark.asyncio
async def test_patch_duplicate_collides_409(client, org_admin_headers, branch, db):
    a = Patient(id=uuid.uuid4(), branch_id=branch.id, name="Amma",
                phone="+919000000022", is_primary=True)
    b = Patient(id=uuid.uuid4(), branch_id=branch.id, name="Nanna",
                phone="+919000000022", is_primary=False)
    db.add_all([a, b]); await db.commit()
    # Rename Nanna -> Amma on the same phone: collides with a.
    r = await client.patch(f"/patients/{b.id}",
                           json={"branch_id": str(branch.id), "name": "Amma"},
                           headers=org_admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "duplicate_patient"


@pytest.mark.asyncio
async def test_patch_cross_branch_404(client, org_admin_headers, other_branch, db):
    p = Patient(id=uuid.uuid4(), branch_id=other_branch.id, name="X", phone="+919000000023")
    db.add(p); await db.commit()
    # org_admin_headers belongs to `branch`, not other_branch — but they claim their own branch.
    r = await client.patch(f"/patients/{p.id}",
                           json={"branch_id": str(other_branch.id), "name": "Y"},
                           headers=org_admin_headers)
    assert r.status_code in (403, 404)
```

Reuse whatever `client`, `org_admin_headers`, `branch`, `doctor`, `other_branch` fixtures already exist in the integration suite (see `tests/integration/test_treatment_notes_api.py` / `conftest.py`). If `other_branch` does not exist, create a second branch inline like `branch`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_patients_router.py -v`
Expected: FAIL — 404 for every request (route not registered).

- [ ] **Step 3: Write the router**

Create `backend/routers/patients.py`:

```python
"""Patient Information view (clinic-only). GET a branch's patients with their
last-seen doctor; PATCH name/age/phone with a duplicate guard.

RULE 1: every route branch-scoped (assert_branch_access); super_admin denied
(forbid_admin). RULE 9: name/age/phone are PII — never logged.
"""
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user, forbid_admin
from backend.middleware.branch_guard import assert_branch_access
from backend.models.schema import Patient, Token, Doctor
from backend.services.validators import normalize_indian_phone

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(forbid_admin)])


class PatientRow(BaseModel):
    id: uuid.UUID
    name: str
    age: int | None
    phone: str | None
    is_primary: bool
    last_doctor: str | None


class PatientEdit(BaseModel):
    branch_id: uuid.UUID
    name: str | None = Field(None, min_length=1, max_length=255)
    age: int | None = Field(None, ge=0, le=120)
    phone: str | None = None


@router.get("/branches/{branch_id}/patients")
async def list_patients(
    branch_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_branch_access(user, str(branch_id), db)

    # Latest token per patient (date desc, created_at desc) -> doctor name.
    # One pass: rank tokens per patient, keep rank 1, join the doctor.
    ranked = (
        select(
            Token.patient_id.label("pid"),
            Doctor.name.label("doctor_name"),
            func.row_number().over(
                partition_by=Token.patient_id,
                order_by=(Token.date.desc(), Token.created_at.desc()),
            ).label("rn"),
        )
        .join(Doctor, Token.doctor_id == Doctor.id)
        .where(Token.branch_id == branch_id)
        .subquery()
    )
    last_doc = select(ranked.c.pid, ranked.c.doctor_name).where(ranked.c.rn == 1).subquery()

    rows = (
        await db.execute(
            select(Patient, last_doc.c.doctor_name)
            .outerjoin(last_doc, last_doc.c.pid == Patient.id)
            .where(Patient.branch_id == branch_id)
            .order_by(func.lower(Patient.name))
        )
    ).all()

    patients = [
        PatientRow(
            id=p.id, name=p.name, age=p.age, phone=p.phone,
            is_primary=p.is_primary, last_doctor=doc_name,
        )
        for (p, doc_name) in rows
    ]
    return {"patients": patients}


@router.patch("/{patient_id}")
async def edit_patient(
    patient_id: uuid.UUID,
    body: PatientEdit,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PatientRow:
    await assert_branch_access(user, str(body.branch_id), db)
    patient = (
        await db.execute(
            select(Patient).where(
                Patient.id == patient_id, Patient.branch_id == body.branch_id
            )
        )
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found in branch")

    new_name = body.name.strip() if body.name is not None else patient.name
    new_phone = patient.phone
    if body.phone is not None:
        try:
            new_phone = normalize_indian_phone(body.phone)
        except ValueError:
            raise HTTPException(status_code=422, detail="phone must be a 10-digit Indian mobile")

    # Duplicate guard: another patient in this branch with the same (phone, lower(name)).
    if (new_name.lower() != patient.name.lower()) or (new_phone != patient.phone):
        if new_phone is not None:
            clash = (
                await db.execute(
                    select(Patient.id).where(
                        and_(
                            Patient.branch_id == body.branch_id,
                            Patient.phone == new_phone,
                            func.lower(Patient.name) == new_name.lower(),
                            Patient.id != patient.id,
                        )
                    )
                )
            ).first()
            if clash is not None:
                raise HTTPException(status_code=409, detail="duplicate_patient")

    phone_changed = new_phone != patient.phone
    patient.name = new_name
    patient.phone = new_phone
    if body.age is not None:
        patient.age = body.age

    # Re-evaluate ownership if the phone moved: if the new phone has no other
    # primary, this patient becomes its owner.
    if phone_changed and new_phone is not None:
        has_primary = (
            await db.execute(
                select(Patient.id).where(
                    and_(
                        Patient.branch_id == body.branch_id,
                        Patient.phone == new_phone,
                        Patient.is_primary.is_(True),
                        Patient.id != patient.id,
                    )
                )
            )
        ).first()
        patient.is_primary = has_primary is None

    await db.commit()
    logger.info("patient_edited", branch_id=str(body.branch_id), patient_id=str(patient.id),
                phone_changed=phone_changed)
    return PatientRow(
        id=patient.id, name=patient.name, age=patient.age, phone=patient.phone,
        is_primary=patient.is_primary, last_doctor=None,
    )
```

- [ ] **Step 4: Register the router**

In `backend/main.py`, next to the other `from backend.routers import ...` lines (~line 248) add:

```python
from backend.routers import patients as patients_router
```

And with the other `app.include_router(...)` calls (~line 260) add:

```python
app.include_router(patients_router.router, prefix="/patients", tags=["patients"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/integration/test_patients_router.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/routers/patients.py backend/main.py tests/integration/test_patients_router.py
git commit -m "feat(patients): branch-scoped Patient Information router — list + edit (409 dup)"
```

---

## Task 6: Frontend Patient Information page (list + inline edit + nav)

**Files:**
- Create: `frontend/src/api/patients.js`
- Create: `frontend/src/pages/Patients.jsx`
- Modify: `frontend/src/App.jsx:10` (import) and `:71-78` (route)
- Modify: `frontend/src/components/Shell.jsx:5-29` (nav entries)

**Interfaces:**
- Consumes: `GET /patients/branches/{branchId}/patients`, `PATCH /patients/{patientId}` (Task 5).

- [ ] **Step 1: Write the API client**

Create `frontend/src/api/patients.js` (mirror `frontend/src/api/treatment.js`):

```javascript
import { api } from "./client";

export const listPatients = (branchId) =>
  api.get(`/patients/branches/${branchId}/patients`).then((r) => r.data.patients);

export const editPatient = (patientId, payload) =>
  api.patch(`/patients/${patientId}`, payload).then((r) => r.data);
```

- [ ] **Step 2: Write the page**

Create `frontend/src/pages/Patients.jsx`. Read `frontend/src/pages/Treatments.jsx` first to match how it resolves `branchId` (from `useAuth`), its toast/query patterns, and styling classes. Implement a table (Name · Age · Phone · Last doctor · Primary chip) with a per-row edit toggle that PATCHes name/age/phone and shows the 409 message:

```jsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../hooks/useAuth.jsx";
import { listPatients, editPatient } from "../api/patients.js";

export default function Patients() {
  const { user } = useAuth();
  const branchId = user?.branch_id;
  const qc = useQueryClient();
  const { data: patients = [], isLoading } = useQuery({
    queryKey: ["patients", branchId],
    queryFn: () => listPatients(branchId),
    enabled: !!branchId,
  });
  const [editing, setEditing] = useState(null); // patient id
  const [form, setForm] = useState({ name: "", age: "", phone: "" });
  const [err, setErr] = useState("");

  const mut = useMutation({
    mutationFn: ({ id, payload }) => editPatient(id, payload),
    onSuccess: () => { setEditing(null); setErr(""); qc.invalidateQueries({ queryKey: ["patients", branchId] }); },
    onError: (e) => setErr(
      e?.response?.status === 409
        ? "Another patient already has this name + number"
        : "Could not save — check the details"),
  });

  const startEdit = (p) => {
    setErr("");
    setEditing(p.id);
    setForm({ name: p.name || "", age: p.age ?? "", phone: p.phone || "" });
  };
  const save = (p) => {
    const payload = { branch_id: branchId, name: form.name };
    if (form.age !== "") payload.age = Number(form.age);
    if (form.phone !== "") payload.phone = form.phone;
    mut.mutate({ id: p.id, payload });
  };

  if (isLoading) return <div className="p-4">Loading…</div>;

  return (
    <div className="mx-auto max-w-4xl p-4">
      <h1 className="mb-4 font-brand text-2xl">Patient Information</h1>
      {err && <p className="mb-3 text-sm text-red-600">{err}</p>}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left">
            <tr>
              <th className="p-3">Name</th><th className="p-3">Age</th>
              <th className="p-3">Phone</th><th className="p-3">Last doctor</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {patients.map((p) => (
              <tr key={p.id} className="border-t">
                {editing === p.id ? (
                  <>
                    <td className="p-2"><input className="w-full rounded border px-2 py-1"
                      value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></td>
                    <td className="p-2"><input className="w-16 rounded border px-2 py-1" value={form.age}
                      onChange={(e) => setForm({ ...form, age: e.target.value })} /></td>
                    <td className="p-2"><input className="w-full rounded border px-2 py-1" value={form.phone}
                      onChange={(e) => setForm({ ...form, phone: e.target.value })} /></td>
                    <td className="p-2 text-slate-400">{p.last_doctor || "—"}</td>
                    <td className="p-2 whitespace-nowrap">
                      <button className="btn-primary px-3 py-1" onClick={() => save(p)} disabled={mut.isPending}>Save</button>
                      <button className="btn-ghost ml-2 px-3 py-1" onClick={() => { setEditing(null); setErr(""); }}>Cancel</button>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="p-3">{p.name}{p.is_primary && <span className="ml-2 rounded bg-teal/10 px-1.5 py-0.5 text-xs text-teal">primary</span>}</td>
                    <td className="p-3">{p.age ?? "—"}</td>
                    <td className="p-3">{p.phone || "—"}</td>
                    <td className="p-3">{p.last_doctor || "—"}</td>
                    <td className="p-3"><button className="btn-ghost px-3 py-1" onClick={() => startEdit(p)}>Edit</button></td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

Note: confirm `user.branch_id` is the correct field on the auth user (check how `Treatments.jsx` gets the branch id) and adjust. Reuse existing button classes (`btn-primary`, `btn-ghost`) — confirm they exist in the app's CSS as used elsewhere.

- [ ] **Step 3: Add the route**

In `frontend/src/App.jsx`, add the import near line 10:

```jsx
import Patients from "./pages/Patients.jsx";
```

Add the route after the `/treatments` route (~line 78):

```jsx
        <Route
          path="/patients"
          element={
            <Protected roles={["org_admin", "receptionist"]}>
              <Patients />
            </Protected>
          }
        />
```

- [ ] **Step 4: Add the nav entries**

In `frontend/src/components/Shell.jsx`, add `{ to: "/patients", label: "Patients" }` to the `receptionist` and `org_admin` arrays in `NAV` (after their `treatments` entry).

- [ ] **Step 5: Build to verify**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/patients.js frontend/src/pages/Patients.jsx frontend/src/App.jsx frontend/src/components/Shell.jsx
git commit -m "feat(pwa): Patient Information page — list + inline edit + nav"
```

---

## Task 7: recognize_caller_name returns the primary's name

**Files:**
- Modify: `agent/tools/booking_tools.py:1064-1088`
- Test: `tests/integration/test_recognize_primary.py` (new)

**Interfaces:**
- Consumes: `Patient.is_primary` (Task 1).
- Produces: `recognize_caller_name(branch_id, phone, db)` returns the `is_primary` patient's name when several patients share the phone (instead of `None`); still `None` when no patient / no primary on file.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_recognize_primary.py`:

```python
import uuid
import pytest

from backend.models.schema import Branch, Patient, Organization
from agent.tools.booking_tools import recognize_caller_name


@pytest.mark.asyncio
async def test_returns_primary_when_multiple_names(db):
    org = Organization(id=uuid.uuid4(), name="Org", plan="clinic")
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="Br", timezone="Asia/Kolkata")
    db.add_all([org, br]); await db.flush()
    db.add_all([
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone="+919000000030", is_primary=True),
        Patient(id=uuid.uuid4(), branch_id=br.id, name="Sita", phone="+919000000030", is_primary=False),
    ])
    await db.flush()
    name = await recognize_caller_name(br.id, "+919000000030", db)
    assert name == "Ravi"


@pytest.mark.asyncio
async def test_none_when_no_patient(db):
    org = Organization(id=uuid.uuid4(), name="Org", plan="clinic")
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="Br", timezone="Asia/Kolkata")
    db.add_all([org, br]); await db.flush()
    assert await recognize_caller_name(br.id, "+919000000031", db) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_recognize_primary.py -v`
Expected: FAIL — current code returns `None` for a multi-name phone.

- [ ] **Step 3: Rewrite the query to prefer the primary**

Replace the body of `recognize_caller_name` (from line 1080 `names = (...)` to the return at 1088) with a query that selects `(name, is_primary)` and prefers the primary:

```python
    rows = (
        await db.execute(
            select(Patient.name, Patient.is_primary).where(
                and_(Patient.branch_id == branch_id, Patient.phone.like(f"%{last10}"))
            )
        )
    ).all()
    named = [(n.strip(), pr) for (n, pr) in rows if n and n.strip()]
    if not named:
        return None
    # Primary owns the phone -> greet them by name even on a shared family phone.
    for n, is_primary in named:
        if is_primary:
            return n
    # No primary flagged (legacy row) but exactly one name -> safe to greet.
    distinct = {n for n, _ in named}
    return next(iter(distinct)) if len(distinct) == 1 else None
```

Update the docstring's "Several names ... → None" line to note the primary is now returned.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_recognize_primary.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/tools/booking_tools.py tests/integration/test_recognize_primary.py
git commit -m "feat(agent): recognize_caller_name returns the primary on a shared family phone"
```

---

## Task 8: Known-caller booking flow — self vs. someone-else

**Files:**
- Modify: `agent/livekit_minimal/agent.py:1898-1905` (the `caller_prompt_extra` string)
- Test: `tests/unit/test_known_caller_extra.py` (new)

**Interfaces:**
- Consumes: recognized primary name (Task 7), `confirm_booking(different_person=...)` (existing param).
- Produces: module-level constant `KNOWN_CALLER_BOOKING_EXTRA` (a `str.format` template with a `{name}` field) in `agent/livekit_minimal/agent.py`, used where `caller_prompt_extra` was inlined.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_known_caller_extra.py`:

```python
from agent.livekit_minimal.agent import KNOWN_CALLER_BOOKING_EXTRA


def test_extra_drives_self_vs_other():
    text = KNOWN_CALLER_BOOKING_EXTRA.format(name="Ravi")
    assert "Ravi" in text
    low = text.lower()
    # Must instruct the self/other question and the two branches.
    assert "someone else" in low or "for you" in low
    assert "different_person=true" in low          # family member branch
    assert "different_person=false" in low         # self branch
    # Self branch: no name/age re-asked; phone optional for the other person.
    assert "optional" in low
    assert "age" in low
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_known_caller_extra.py -v`
Expected: FAIL — `ImportError: cannot import name 'KNOWN_CALLER_BOOKING_EXTRA'`.

- [ ] **Step 3: Extract + rewrite the prompt-extra**

Near the top of `agent/livekit_minimal/agent.py` (module scope, with other prompt constants), add:

```python
KNOWN_CALLER_BOOKING_EXTRA = (
    "\n\nCALLER IDENTIFICATION: this number belongs to an EXISTING patient, "
    "{name}, with no upcoming booking. The greeting already welcomed them by "
    "name. After they state the concern, ask ONCE whether the appointment is "
    "for THEMSELVES or for SOMEONE ELSE (spoken naturally in the call's "
    "language, e.g. 'is this appointment for you, or for someone else?').\n"
    "- FOR THEMSELVES: do NOT ask their name or age again — you already know "
    "them as {name}. Take only the concern (route_to_doctor) and their "
    "preferred time, then confirm_booking with patient_name='{name}' and "
    "different_person=false.\n"
    "- FOR SOMEONE ELSE: take that person's NAME and AGE. The phone number is "
    "OPTIONAL — do NOT insist on it (spoken digits are often misheard); if not "
    "given, book under this caller's number. Call confirm_booking with that "
    "person's name and age and different_person=true."
)
```

Replace the inlined assignment at lines 1898-1905:

```python
                    if _known:
                        caller_greeting_name = _known
                        caller_prompt_extra = KNOWN_CALLER_BOOKING_EXTRA.format(name=_known)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_known_caller_extra.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/livekit_minimal/agent.py tests/unit/test_known_caller_extra.py
git commit -m "feat(agent): known-caller booking asks self vs someone-else (self=issue+time, other=name+age+optional phone)"
```

---

## Task 9: FIXLOG rows + full suite

**Files:**
- Modify: `docs/FIXLOG.md`

- [ ] **Step 1: Add FIXLOG rows**

Append one row per Task 1–8 to `docs/FIXLOG.md` (next numbers after the current last row), each: what changed, why, the proving test. Follow the existing row format in that file.

- [ ] **Step 2: Run the full backend suite**

Run: `pytest tests/unit tests/integration -q`
Expected: green except the two known failures (`test_smallest_voice`, `test_confirm_booking_transient_calendar_failure_single_row`).

- [ ] **Step 3: Build the frontend**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add docs/FIXLOG.md
git commit -m "docs: FIXLOG rows for patient dedup + Patient Information view + greet-by-name"
```

---

## Deploy note (gated — do not run without Vinay)

The `y22patientdedup2026` migration must be applied to prod BEFORE the app code that relies on `is_primary` serves traffic. Prod DB provisioning uses create_all + stamp head (memory: alembic chain broken), so for an EXISTING prod DB run `alembic upgrade head` to apply y22; for a fresh DB, create_all builds the column+index and you stamp `y22patientdedup2026`. Confirm with Vinay before deploying.

---

## Self-Review

**Spec coverage:**
- Data model / dedup rule → Task 1 (column+index), Task 2+3 (merge+backfill+migration), Task 4 (is_primary on create). ✓
- find-or-create case-insensitive → already case-insensitive in both paths; Task 4 notes this and only adds is_primary. ✓
- Patient Information GET list (last_doctor, no N+1) → Task 5 (window-function subquery, single query). ✓
- PATCH edit + 409 + 404 + super_admin 403 + phone re-normalize + is_primary re-eval → Task 5. ✓
- Frontend page + api + nav → Task 6. ✓
- recognize_caller_name primary-aware → Task 7. ✓
- Greet-by-name (existing) + known-caller self/other, self=issue+time, other=name+age+optional phone, different_person → Task 8. ✓
- Migration testing (merge, repoint, one primary, index) → Task 2 tests + Task 3. ✓
- Out of scope (UI merge, is_primary UI edit, WhatsApp) → not built. ✓

**Placeholder scan:** No TBD/TODO; every code step shows the code; test bodies are complete. Fixture reuse notes point to real files.

**Type consistency:** `is_primary` (bool) consistent across schema/migration/booking/router/agent. `recognize_caller_name(branch_id, phone, db) -> str | None` unchanged signature. Router response keys (`id,name,age,phone,is_primary,last_doctor`) match the frontend table and the PATCH return. `KNOWN_CALLER_BOOKING_EXTRA.format(name=...)` matches its usage.
