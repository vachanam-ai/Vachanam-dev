# Sub-spec A — Calendar + Receptionist PWA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **CLAUDE.md mandate:** Main thread is orchestrator only. Each task below MUST be dispatched to the agent named in the task header — main thread NEVER edits `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`. Every dispatch logged in `docs/DISPATCHES.md`.

**Spec:** `docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md` (commit `9fd333a`).

**Goal:** Ship real Google Calendar integration + receptionist PWA + admin dashboard + RBAC tightening so a pilot clinic can run end-to-end without WhatsApp.

**Architecture:** DB-first booking with hybrid Cal write (sync inline for slot-doctor, async queue for token-doctor). PWA built on React 18 + Vite 5 + Tailwind 3 + TanStack Query + Workbox + Framer Motion + Sonner + Vaul. RBAC enforces DPDP boundary — Vinay (super_admin) locked out of clinic PII.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / Postgres 16 / Redis 7 / google-api-python-client / React 18 / Vite 5 / Tailwind 3 / TanStack Query v5 / Workbox / Framer Motion / Sonner / Vaul / idb-keyval / zod / Vitest / Playwright.

**Effort:** ~12 working days (28 tasks).

---

## Task index

| # | Task | Dispatch to | Hours |
|---|---|---|---|
| 1 | Pre-flight (Cal sanity test + env + .gitignore) | manual (Vinay) | 0.5 |
| 2 | Alembic migration | database-engineer | 2 |
| 3 | Calendar service (slot-doctor per-patient events) | backend-engineer | 3 |
| 4 | Calendar service (token-doctor recurring event) | backend-engineer | 2 |
| 5 | Calendar write queue table + worker | backend-engineer | 3 |
| 6 | Hybrid sync/async booking helper | backend-engineer | 2 |
| 7 | RBAC tightening (assert_branch_access + forbid_admin + super_admin lockout) | security-engineer | 2 |
| 8 | Doctors router | backend-engineer | 3 |
| 9 | Availability router + cascade flow | backend-engineer | 4 |
| 10 | Walk-in router (preflight + post + hard cap + emergency override) | backend-engineer | 4 |
| 11 | Followup router | backend-engineer | 2 |
| 12 | Branches router (calendar config) | backend-engineer | 1 |
| 13 | Doctor self router (read-only) | backend-engineer | 1.5 |
| 14 | Admin router extensions (lifetime totals + warnings + pnl + contacts) | backend-engineer | 3 |
| 15 | Admin warning scanner job | backend-engineer | 1.5 |
| 16 | CLAUDE.md RULE 4 amendment + TD entries | manual (main thread) | 0.3 |
| 17 | PWA bootstrap (Vite + Tailwind + deps) | frontend-engineer | 2 |
| 18 | Auth bootstrap (Google + JWT + IndexedDB) | frontend-engineer | 2 |
| 19 | Service worker + Workbox + offline plumbing | frontend-engineer | 2 |
| 20 | App shell + routing + role-based nav | frontend-engineer | 2 |
| 21 | Queue page | frontend-engineer | 3 |
| 22 | Walk-in drawer + adaptive form + preflight | frontend-engineer | 4 |
| 23 | Doctors list + edit page | frontend-engineer | 4 |
| 24 | Doctor unavailability drawer | frontend-engineer | 3 |
| 25 | Followup drawer | frontend-engineer | 2 |
| 26 | Admin dashboard (Layout A Mission Control) | frontend-engineer | 5 |
| 27 | Doctor self view | frontend-engineer | 1.5 |
| 28 | Acceptance gate + sprint close | tester + manager | 2 |

---

## Task 1: Pre-flight (manual — Vinay)

**Owner:** Vinay (no agent dispatch — Google Console + Render dashboard work).

- [ ] **Step 1: Confirm `.gitignore` excludes `.superpowers/` + `.env` + `google-service-account.json`** — already verified 2026-06-08, no-op.
- [ ] **Step 2: Create Google Cloud project `vachanam-prod`** in console.cloud.google.com.
- [ ] **Step 3: Enable Calendar API** for the project (APIs & Services → Library → Google Calendar API → Enable).
- [ ] **Step 4: Create service account `vachanam-events`** (IAM & Admin → Service Accounts → Create).
- [ ] **Step 5: Download SA JSON key** → save as `google-service-account.json` in repo root (gitignored).
- [ ] **Step 6: Sanity test** — open personal Gmail Calendar → Settings & Sharing → Share with specific people → add `vachanam-events@vachanam-prod.iam.gserviceaccount.com` with "Make changes to events".
- [ ] **Step 7: Manual probe** — run this Python snippet locally:
  ```python
  from google.oauth2 import service_account
  from googleapiclient.discovery import build
  creds = service_account.Credentials.from_service_account_file(
      "google-service-account.json",
      scopes=["https://www.googleapis.com/auth/calendar.events"],
  )
  svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
  event = svc.events().insert(calendarId="<your-personal-cal-id>", body={
      "summary": "Vachanam probe",
      "start": {"dateTime": "2026-06-20T10:00:00+05:30"},
      "end":   {"dateTime": "2026-06-20T10:30:00+05:30"},
  }).execute()
  print("event id:", event["id"])
  svc.events().delete(calendarId="<your-personal-cal-id>", eventId=event["id"]).execute()
  print("deleted")
  ```
  Expected: prints `event id: ...` then `deleted`. If 403 → personal Gmail share not supported in your region; re-test with a Workspace calendar.
- [ ] **Step 8: Base64 SA JSON for Render env:**
  ```bash
  base64 -w 0 google-service-account.json > sa-b64.txt
  ```
  Copy contents → Render env → `GOOGLE_SA_JSON_B64`.
- [ ] **Step 9: Confirm:** post in chat "pre-flight done" — unblocks Task 2.

---

## Task 2: Alembic migration (database-engineer)

**Dispatch:** `Task(subagent_type="database-engineer", prompt=...)` with this task's full text.

**Files:**
- Create: `alembic/versions/2026_06_09_subspec_a_schema.py`
- Modify: `backend/models/schema.py` (ORM additions)
- Test: `tests/integration/test_subspec_a_migration.py`

- [ ] **Step 1: Write the failing test (schema introspection)**
  ```python
  # tests/integration/test_subspec_a_migration.py
  import pytest
  from sqlalchemy import inspect
  from backend.database import engine
  from backend.models.schema import Doctor, Token, FollowupTask, User
  
  @pytest.mark.asyncio
  async def test_doctor_new_columns(db):
      async with engine.connect() as conn:
          insp = await conn.run_sync(lambda c: inspect(c))
          cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("doctors")})
      for required in [
          "available_weekdays", "post_treatment_followup", "walkins_closed_today_date",
          "calendar_event_id_recurring", "user_id", "invited_email",
      ]:
          assert required in cols, f"missing column: {required}"
  
  @pytest.mark.asyncio
  async def test_doctor_unavailability_table_exists(db):
      async with engine.connect() as conn:
          tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
      assert "doctor_unavailability" in tables
  
  @pytest.mark.asyncio
  async def test_token_new_columns(db):
      async with engine.connect() as conn:
          cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("tokens")})
      for required in ["cancelled_by_user_id", "emergency_reason"]:
          assert required in cols
  
  @pytest.mark.asyncio
  async def test_followup_task_new_columns(db):
      async with engine.connect() as conn:
          cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("followup_tasks")})
      for required in ["task_type", "token_id"]:
          assert required in cols
  
  @pytest.mark.asyncio
  async def test_calendar_write_tasks_table(db):
      async with engine.connect() as conn:
          tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
      assert "calendar_write_tasks" in tables
  
  @pytest.mark.asyncio
  async def test_user_role_enum_has_doctor(db):
      async with engine.connect() as conn:
          result = await conn.execute("SELECT unnest(enum_range(NULL::user_role))")
          vals = {r[0] for r in result}
      assert "doctor" in vals
  
  @pytest.mark.asyncio
  async def test_compound_indexes_present(db):
      async with engine.connect() as conn:
          idx = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("tokens")})
      assert "ix_tokens_branch_date" in idx
      assert "ix_tokens_branch_doctor_date" in idx
  ```

- [ ] **Step 2: Run tests — confirm FAIL** with "missing column / table / index".
  ```bash
  pytest tests/integration/test_subspec_a_migration.py -v
  ```

- [ ] **Step 3: Generate Alembic migration skeleton**
  ```bash
  alembic revision -m "subspec_a_schema"
  ```
  Edit the generated file `alembic/versions/2026_06_09_<hash>_subspec_a_schema.py`:
  ```python
  """subspec_a_schema
  
  Sub-spec A schema: Calendar + Receptionist PWA + RBAC.
  See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §3.
  """
  from alembic import op
  import sqlalchemy as sa
  from sqlalchemy.dialects import postgresql
  
  revision = "<auto-generated>"
  down_revision = "<previous head>"
  branch_labels = None
  depends_on = None
  
  
  def upgrade() -> None:
      # 3.1 Doctor additions
      op.add_column("doctors", sa.Column("available_weekdays", postgresql.JSONB, nullable=False, server_default=sa.text("'[0,1,2,3,4,5,6]'::jsonb")))
      op.add_column("doctors", sa.Column("post_treatment_followup", sa.Boolean, nullable=False, server_default=sa.false()))
      op.add_column("doctors", sa.Column("walkins_closed_today_date", sa.Date, nullable=True))
      op.add_column("doctors", sa.Column("calendar_event_id_recurring", sa.String(255), nullable=True))
      op.add_column("doctors", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
      op.add_column("doctors", sa.Column("invited_email", sa.String(255), nullable=True))
      op.create_foreign_key("fk_doctors_user_id", "doctors", "users", ["user_id"], ["id"], ondelete="SET NULL")
      op.create_unique_constraint("uq_doctors_user_id", "doctors", ["user_id"])
  
      # 3.2 doctor_unavailability
      op.create_table(
          "doctor_unavailability",
          sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
          sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
          sa.Column("doctor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False),
          sa.Column("date", sa.Date, nullable=False),
          sa.Column("reason", sa.Text, nullable=True),
          sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
          sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
          sa.UniqueConstraint("doctor_id", "date", name="uq_doctor_unavailability_doctor_date"),
      )
      op.create_index("ix_doctor_unavailability_branch_date", "doctor_unavailability", ["branch_id", "date"])
  
      # 3.3 FollowupTask additions
      op.add_column("followup_tasks", sa.Column("task_type", sa.String(30), nullable=False, server_default="post_appt_check"))
      op.add_column("followup_tasks", sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True))
      op.create_foreign_key("fk_followup_tasks_token_id", "followup_tasks", "tokens", ["token_id"], ["id"], ondelete="RESTRICT")
  
      # 3.4 Token additions
      op.add_column("tokens", sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
      op.add_column("tokens", sa.Column("emergency_reason", sa.Text, nullable=True))
  
      # 3.5 calendar_write_tasks
      op.create_table(
          "calendar_write_tasks",
          sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
          sa.Column("branch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
          sa.Column("token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tokens.id", ondelete="RESTRICT"), nullable=False),
          sa.Column("operation", sa.String(20), nullable=False),
          sa.Column("payload_json", postgresql.JSONB, nullable=False),
          sa.Column("google_event_id", sa.String(255), nullable=True),
          sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
          sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
          sa.Column("last_error", sa.Text, nullable=True),
          sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
          sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
          sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
      )
      op.create_index("ix_calendar_tasks_status_next", "calendar_write_tasks", ["status", "next_attempt_at"])
  
      # 3.6 user_role enum value (must be outside transaction)
      op.execute("COMMIT")
      op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'doctor'")
      op.execute("BEGIN")
  
      # 3.7 compound indexes
      op.create_index("ix_tokens_branch_date", "tokens", ["branch_id", "date"])
      op.create_index("ix_tokens_branch_doctor_date", "tokens", ["branch_id", "doctor_id", "date"])
  
  
  def downgrade() -> None:
      op.drop_index("ix_tokens_branch_doctor_date", table_name="tokens")
      op.drop_index("ix_tokens_branch_date", table_name="tokens")
      # NOTE: cannot easily drop enum value 'doctor' in Postgres; leave it
      op.drop_index("ix_calendar_tasks_status_next", table_name="calendar_write_tasks")
      op.drop_table("calendar_write_tasks")
      op.drop_column("tokens", "emergency_reason")
      op.drop_column("tokens", "cancelled_by_user_id")
      op.drop_constraint("fk_followup_tasks_token_id", "followup_tasks", type_="foreignkey")
      op.drop_column("followup_tasks", "token_id")
      op.drop_column("followup_tasks", "task_type")
      op.drop_index("ix_doctor_unavailability_branch_date", table_name="doctor_unavailability")
      op.drop_table("doctor_unavailability")
      op.drop_constraint("uq_doctors_user_id", "doctors", type_="unique")
      op.drop_constraint("fk_doctors_user_id", "doctors", type_="foreignkey")
      for col in ["invited_email", "user_id", "calendar_event_id_recurring",
                  "walkins_closed_today_date", "post_treatment_followup", "available_weekdays"]:
          op.drop_column("doctors", col)
  ```

- [ ] **Step 4: Update ORM models** — add the new columns to `Doctor`, `Token`, `FollowupTask` SQLAlchemy classes in `backend/models/schema.py` AND add new `DoctorUnavailability` + `CalendarWriteTask` models matching the migration. (Skim spec §3 for column types — match exactly.)

- [ ] **Step 5: Run migration** against test DB:
  ```bash
  TEST_DATABASE_URL=postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_test \
    alembic upgrade head
  ```
  Expected: applies cleanly.

- [ ] **Step 6: Run tests — confirm PASS**
  ```bash
  pytest tests/integration/test_subspec_a_migration.py -v
  ```
  Expected: 7/7 pass.

- [ ] **Step 7: Run full test suite — no regressions**
  ```bash
  pytest tests/ -v
  ```
  Expected: all 207+ existing pass.

- [ ] **Step 8: Commit**
  ```bash
  git add alembic/versions/ backend/models/schema.py tests/integration/test_subspec_a_migration.py
  git commit -m "feat(db): sub-spec A schema (Doctor weekdays + unavailability + followup typing + Cal queue + RBAC)"
  ```

---

## Task 3: Calendar service — slot-doctor per-patient events (backend-engineer)

**Files:**
- Create: `backend/services/calendar_service.py` (real impl, replaces stub)
- Delete: `agent/services/calendar_stub.py` + `backend/services/calendar_service.py` (the old stub — replace, don't append)
- Create: `agent/services/calendar_proxy.py` (re-export shim for agent runtime)
- Test: `tests/unit/test_calendar_service_create.py`

- [ ] **Step 1: Write failing tests**
  ```python
  # tests/unit/test_calendar_service_create.py
  from datetime import datetime
  from unittest.mock import MagicMock, patch
  import pytest
  from backend.services.calendar_service import GoogleCalendarService, CalendarNotConfiguredError
  
  @pytest.fixture
  def svc():
      with patch("backend.services.calendar_service.build") as mock_build, \
           patch("backend.services.calendar_service.service_account.Credentials.from_service_account_file"):
          mock_service = MagicMock()
          mock_build.return_value = mock_service
          s = GoogleCalendarService(sa_json_path="/fake/path.json")
          s._service = mock_service
          yield s, mock_service
  
  @pytest.mark.asyncio
  async def test_create_event_summary_format(svc):
      s, mock = svc
      mock.events().insert().execute.return_value = {"id": "evt_abc"}
      event_id = await s.create_booking_event(
          calendar_id="cal_id",
          patient_first_name="Suresh",
          patient_phone_last4="5891",
          appointment_dt=datetime(2026, 6, 20, 15, 0),
          duration_minutes=30,
          doctor_name="Dr Reddy",
      )
      assert event_id == "evt_abc"
      call_args = mock.events().insert.call_args
      body = call_args.kwargs.get("body") or call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["body"]
      assert "Apt — Suresh (xx5891)" in body["summary"]
      assert body.get("description", "") == ""  # PII rule
  
  @pytest.mark.asyncio
  async def test_create_event_no_full_phone_in_summary(svc):
      s, mock = svc
      mock.events().insert().execute.return_value = {"id": "evt_xyz"}
      await s.create_booking_event(
          calendar_id="c", patient_first_name="Ravi", patient_phone_last4="9999",
          appointment_dt=datetime(2026, 6, 20, 10, 0), duration_minutes=15, doctor_name="Dr A",
      )
      body_summary = mock.events().insert.call_args.kwargs["body"]["summary"]
      assert "+91" not in body_summary
      assert "9XXXX" not in body_summary
      # last 4 only:
      assert "xx9999" in body_summary
  
  @pytest.mark.asyncio
  async def test_create_event_raises_on_no_calendar_id(svc):
      s, _ = svc
      with pytest.raises(CalendarNotConfiguredError):
          await s.create_booking_event(
              calendar_id=None, patient_first_name="X", patient_phone_last4="1234",
              appointment_dt=datetime(2026, 6, 20, 10, 0), duration_minutes=15, doctor_name="Dr",
          )
  ```

- [ ] **Step 2: Run tests — confirm FAIL** with ImportError / not implemented.

- [ ] **Step 3: Implement `backend/services/calendar_service.py`**
  ```python
  """Real Google Calendar service. Replaces calendar_stub.
  
  See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.
  """
  from __future__ import annotations
  import asyncio
  import base64
  from datetime import datetime, time, timedelta
  from pathlib import Path
  from typing import Optional
  import structlog
  from google.oauth2 import service_account
  from googleapiclient.discovery import build
  from googleapiclient.errors import HttpError
  from backend.config import settings
  
  logger = structlog.get_logger()
  
  WEEKDAY_TO_RFC5545 = {0: "MO", 1: "TU", 2: "WE", 3: "TH", 4: "FR", 5: "SA", 6: "SU"}
  
  
  class CalendarNotConfiguredError(Exception):
      """Branch or doctor has no calendar_id set."""
  
  
  class CalendarWriteFailed(Exception):
      """Wraps any underlying Google API failure for retry logic to catch."""
  
  
  class GoogleCalendarService:
      def __init__(self, sa_json_path: Optional[str] = None):
          path = sa_json_path or self._resolve_sa_path()
          creds = service_account.Credentials.from_service_account_file(
              path, scopes=["https://www.googleapis.com/auth/calendar.events"],
          )
          self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
  
      @staticmethod
      def _resolve_sa_path() -> str:
          if settings.google_sa_json_b64:
              tmp = Path("/tmp/google-sa.json")
              if not tmp.exists():
                  tmp.write_bytes(base64.b64decode(settings.google_sa_json_b64))
              return str(tmp)
          return settings.google_application_credentials
  
      async def create_booking_event(
          self, *, calendar_id: Optional[str], patient_first_name: str,
          patient_phone_last4: str, appointment_dt: datetime, duration_minutes: int,
          doctor_name: str,
      ) -> str:
          if not calendar_id:
              raise CalendarNotConfiguredError("calendar_id is None")
          body = {
              "summary": f"Apt — {patient_first_name} (xx{patient_phone_last4})",
              "description": "",
              "start": {"dateTime": appointment_dt.isoformat(), "timeZone": "Asia/Kolkata"},
              "end":   {"dateTime": (appointment_dt + timedelta(minutes=duration_minutes)).isoformat(), "timeZone": "Asia/Kolkata"},
          }
          try:
              event = await asyncio.to_thread(
                  lambda: self._service.events().insert(calendarId=calendar_id, body=body).execute()
              )
              logger.info("calendar_create_success", calendar_id=calendar_id, event_id=event["id"])
              return event["id"]
          except HttpError as e:
              logger.error("calendar_create_failed", error=str(e), calendar_id=calendar_id)
              raise CalendarWriteFailed(str(e)) from e
  
      async def delete_event(self, calendar_id: str, event_id: str) -> None:
          try:
              await asyncio.to_thread(
                  lambda: self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
              )
          except HttpError as e:
              # 404 = already deleted; treat as success
              if getattr(e.resp, "status", None) == 404:
                  return
              raise CalendarWriteFailed(str(e)) from e
  
      async def update_event(self, calendar_id: str, event_id: str, new_dt: datetime, duration_minutes: int) -> None:
          patch = {
              "start": {"dateTime": new_dt.isoformat(), "timeZone": "Asia/Kolkata"},
              "end":   {"dateTime": (new_dt + timedelta(minutes=duration_minutes)).isoformat(), "timeZone": "Asia/Kolkata"},
          }
          try:
              await asyncio.to_thread(
                  lambda: self._service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
              )
          except HttpError as e:
              raise CalendarWriteFailed(str(e)) from e
  ```

- [ ] **Step 4: Replace old stub** — delete `agent/services/calendar_stub.py`. Create `agent/services/calendar_proxy.py`:
  ```python
  """Re-exports backend Calendar service for agent runtime.
  Agent + backend share same google-api-python-client install (both have it in requirements.txt).
  """
  from backend.services.calendar_service import GoogleCalendarService, CalendarNotConfiguredError, CalendarWriteFailed
  
  __all__ = ["GoogleCalendarService", "CalendarNotConfiguredError", "CalendarWriteFailed"]
  ```
  Update `agent/requirements.txt` — add `google-api-python-client>=2.0.0` + `google-auth>=2.0.0`.
  Update `agent/tools/booking_tools.py` — change `from agent.services.calendar_stub import CalendarService` to `from agent.services.calendar_proxy import GoogleCalendarService as CalendarService` (or refactor calls to new method signature).

- [ ] **Step 5: Update `backend/config.py`** — add:
  ```python
  google_sa_json_b64: str | None = None
  google_application_credentials: str = "./google-service-account.json"
  ```

- [ ] **Step 6: Run tests — confirm PASS**
  ```bash
  pytest tests/unit/test_calendar_service_create.py -v
  ```

- [ ] **Step 7: Delete obsolete stub tests** — remove `tests/unit/test_calendar_service_stub.py` and `tests/unit/test_stub_services.py` (or update to reference new impl).

- [ ] **Step 8: Commit**
  ```bash
  git add backend/services/calendar_service.py backend/config.py agent/services/calendar_proxy.py agent/requirements.txt agent/tools/booking_tools.py tests/unit/
  git rm agent/services/calendar_stub.py
  git commit -m "feat(calendar): real Google Calendar service replaces stub (slot-doctor per-patient events)"
  ```

---

## Task 4: Calendar service — token-doctor recurring event (backend-engineer)

**Files:**
- Modify: `backend/services/calendar_service.py` (add `upsert_doctor_hours_event`)
- Test: `tests/unit/test_calendar_service_doctor_hours.py`

- [ ] **Step 1: Write failing tests**
  ```python
  # tests/unit/test_calendar_service_doctor_hours.py
  from datetime import time
  from unittest.mock import MagicMock, patch
  import pytest
  from backend.services.calendar_service import GoogleCalendarService
  
  @pytest.fixture
  def svc():
      with patch("backend.services.calendar_service.build") as mock_build, \
           patch("backend.services.calendar_service.service_account.Credentials.from_service_account_file"):
          mock_service = MagicMock()
          mock_build.return_value = mock_service
          s = GoogleCalendarService(sa_json_path="/fake.json")
          s._service = mock_service
          yield s, mock_service
  
  @pytest.mark.asyncio
  async def test_create_recurring_event_when_no_existing(svc):
      s, mock = svc
      mock.events().insert().execute.return_value = {"id": "evt_recurring_123"}
      event_id = await s.upsert_doctor_hours_event(
          calendar_id="cal", doctor_name="Dr Sharma",
          working_hours_start=time(9, 0), working_hours_end=time(13, 0),
          available_weekdays=[0, 2, 4],  # Mon, Wed, Fri
          existing_event_id=None,
      )
      assert event_id == "evt_recurring_123"
      body = mock.events().insert.call_args.kwargs["body"]
      assert "Dr Sharma" in body["summary"]
      assert any("RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR" in r for r in body["recurrence"])
  
  @pytest.mark.asyncio
  async def test_update_existing_recurring_event(svc):
      s, mock = svc
      mock.events().patch().execute.return_value = {"id": "evt_existing"}
      event_id = await s.upsert_doctor_hours_event(
          calendar_id="cal", doctor_name="Dr Sharma",
          working_hours_start=time(10, 0), working_hours_end=time(14, 0),
          available_weekdays=[1, 3],
          existing_event_id="evt_existing",
      )
      assert event_id == "evt_existing"
      mock.events().patch.assert_called()
  ```

- [ ] **Step 2: Run tests — confirm FAIL** with AttributeError (`upsert_doctor_hours_event` not defined).

- [ ] **Step 3: Add method to `backend/services/calendar_service.py`**
  ```python
      async def upsert_doctor_hours_event(
          self, *, calendar_id: str, doctor_name: str,
          working_hours_start: time, working_hours_end: time,
          available_weekdays: list[int], existing_event_id: Optional[str],
      ) -> str:
          weekday_codes = ",".join(WEEKDAY_TO_RFC5545[w] for w in sorted(set(available_weekdays)))
          # Use a fixed anchor date (today) for the recurring event's first instance.
          from datetime import date as _date
          anchor = _date.today()
          start_dt = datetime.combine(anchor, working_hours_start)
          end_dt = datetime.combine(anchor, working_hours_end)
          body = {
              "summary": f"Dr {doctor_name} — clinic hours",
              "description": "",
              "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
              "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Kolkata"},
              "recurrence": [f"RRULE:FREQ=WEEKLY;BYDAY={weekday_codes}"],
          }
          try:
              if existing_event_id:
                  event = await asyncio.to_thread(
                      lambda: self._service.events().patch(calendarId=calendar_id, eventId=existing_event_id, body=body).execute()
                  )
              else:
                  event = await asyncio.to_thread(
                      lambda: self._service.events().insert(calendarId=calendar_id, body=body).execute()
                  )
              logger.info("calendar_doctor_hours_upsert", calendar_id=calendar_id, event_id=event["id"], weekdays=weekday_codes)
              return event["id"]
          except HttpError as e:
              raise CalendarWriteFailed(str(e)) from e
  ```

- [ ] **Step 4: Run tests — confirm PASS**
  ```bash
  pytest tests/unit/test_calendar_service_doctor_hours.py -v
  ```

- [ ] **Step 5: Commit**
  ```bash
  git add backend/services/calendar_service.py tests/unit/test_calendar_service_doctor_hours.py
  git commit -m "feat(calendar): token-doctor recurring 'clinic hours' event with RRULE"
  ```

---

## Task 5: Calendar write queue + worker (backend-engineer)

**Files:**
- Create: `backend/jobs/calendar_writer.py`
- Modify: `backend/main.py` (lifespan registers job)
- Test: `tests/unit/test_calendar_writer_backoff.py` + `tests/integration/test_calendar_writer_e2e.py`

- [ ] **Step 1: Write failing tests** for backoff schedule + permanent fail transition.
  ```python
  # tests/unit/test_calendar_writer_backoff.py
  from datetime import datetime, timedelta
  from unittest.mock import AsyncMock, patch
  import pytest
  from backend.jobs.calendar_writer import _compute_next_attempt, _process_one_task, BACKOFF_SECONDS
  
  def test_backoff_schedule():
      # attempts=1 → 5s, 2 → 30s, 3 → 5min, 4 → 60min
      assert BACKOFF_SECONDS == [5, 30, 300, 3600]
      base = datetime(2026, 6, 9, 10, 0, 0)
      assert _compute_next_attempt(1, base) == base + timedelta(seconds=5)
      assert _compute_next_attempt(2, base) == base + timedelta(seconds=30)
      assert _compute_next_attempt(3, base) == base + timedelta(seconds=300)
      assert _compute_next_attempt(4, base) == base + timedelta(seconds=3600)
  
  @pytest.mark.asyncio
  async def test_permanent_fail_after_5_attempts(db):
      from backend.models.schema import CalendarWriteTask
      task = CalendarWriteTask(
          branch_id="<uuid>", token_id="<uuid>", operation="create",
          payload_json={}, attempts=4, status="pending",
      )
      db.add(task); await db.commit()
      with patch("backend.jobs.calendar_writer._do_calendar_op", side_effect=Exception("simulated")):
          await _process_one_task(db, task)
      await db.refresh(task)
      assert task.status == "failed_permanent"
      assert task.attempts == 5
  ```

- [ ] **Step 2: Run — confirm FAIL** (module not found).

- [ ] **Step 3: Implement worker** `backend/jobs/calendar_writer.py`:
  ```python
  """APScheduler job: drain calendar_write_tasks queue with exponential backoff.
  
  See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.8.
  """
  from datetime import datetime, timedelta
  from typing import Optional
  import structlog
  from sqlalchemy import select
  from backend.database import AsyncSessionLocal
  from backend.models.schema import CalendarWriteTask, Token
  from backend.services.calendar_service import GoogleCalendarService, CalendarWriteFailed
  from backend.services.admin_alert import alert_admin
  
  logger = structlog.get_logger()
  BACKOFF_SECONDS = [5, 30, 300, 3600]  # after attempt 1, 2, 3, 4
  MAX_ATTEMPTS = 5
  BATCH = 50
  
  
  def _compute_next_attempt(attempts: int, now: datetime) -> datetime:
      return now + timedelta(seconds=BACKOFF_SECONDS[attempts - 1])
  
  
  async def _do_calendar_op(svc: GoogleCalendarService, task: CalendarWriteTask) -> Optional[str]:
      p = task.payload_json
      if task.operation == "create":
          return await svc.create_booking_event(
              calendar_id=p["calendar_id"],
              patient_first_name=p["patient_first_name"],
              patient_phone_last4=p["patient_phone_last4"],
              appointment_dt=datetime.fromisoformat(p["appointment_dt"]),
              duration_minutes=p["duration_minutes"],
              doctor_name=p["doctor_name"],
          )
      if task.operation == "delete":
          if task.google_event_id:
              await svc.delete_event(p["calendar_id"], task.google_event_id)
          return None
      if task.operation == "update":
          await svc.update_event(
              p["calendar_id"], task.google_event_id,
              datetime.fromisoformat(p["appointment_dt"]), p["duration_minutes"],
          )
          return None
      raise ValueError(f"unknown operation: {task.operation}")
  
  
  async def _process_one_task(db, task: CalendarWriteTask) -> None:
      task.status = "in_progress"; await db.commit()
      svc = GoogleCalendarService()
      try:
          event_id = await _do_calendar_op(svc, task)
          task.status = "done"
          if event_id:
              task.google_event_id = event_id
              token = await db.get(Token, task.token_id)
              if token:
                  token.google_calendar_event_id = event_id
          await db.commit()
          logger.info("calendar_task_done", task_id=str(task.id), operation=task.operation)
      except Exception as e:
          task.attempts += 1
          task.last_error = str(e)[:500]
          if task.attempts >= MAX_ATTEMPTS:
              task.status = "failed_permanent"
              await db.commit()
              await alert_admin("calendar_write_failed_permanent", task.branch_id, task.token_id)
              logger.error("calendar_task_failed_permanent", task_id=str(task.id), error=task.last_error)
          else:
              task.next_attempt_at = _compute_next_attempt(task.attempts, datetime.utcnow())
              task.status = "pending"
              await db.commit()
              logger.warning("calendar_task_retry", task_id=str(task.id), attempt=task.attempts, next=task.next_attempt_at.isoformat())
  
  
  async def run_calendar_writer() -> None:
      """Entry point for APScheduler — every 30s."""
      async with AsyncSessionLocal() as db:
          stmt = select(CalendarWriteTask).where(
              CalendarWriteTask.status == "pending",
              CalendarWriteTask.next_attempt_at <= datetime.utcnow(),
          ).limit(BATCH)
          result = await db.execute(stmt)
          for task in result.scalars().all():
              await _process_one_task(db, task)
  ```

- [ ] **Step 4: Create `backend/services/admin_alert.py`** — minimal stub that logs CRITICAL + writes audit row (real email/SMS deferred to TD):
  ```python
  import structlog
  from backend.middleware.audit import audit_event
  logger = structlog.get_logger()
  
  async def alert_admin(event: str, branch_id, token_id=None) -> None:
      logger.critical("admin_alert", event=event, branch_id=str(branch_id), token_id=str(token_id) if token_id else None)
      await audit_event(event=f"admin.alert.{event}", branch_id=branch_id, metadata={"token_id": str(token_id) if token_id else None})
  ```

- [ ] **Step 5: Register in `backend/main.py` lifespan**
  ```python
  scheduler.add_job(run_calendar_writer, IntervalTrigger(seconds=30), id="calendar_writer", replace_existing=True)
  ```

- [ ] **Step 6: Run unit tests — confirm PASS**
  ```bash
  pytest tests/unit/test_calendar_writer_backoff.py -v
  ```

- [ ] **Step 7: Commit**
  ```bash
  git add backend/jobs/calendar_writer.py backend/services/admin_alert.py backend/main.py tests/
  git commit -m "feat(calendar): async write queue + worker with 5-attempt backoff + admin alert on permanent fail"
  ```

---

## Task 6: Hybrid sync/async booking helper (backend-engineer)

**Files:**
- Create: `backend/services/booking_calendar.py`
- Test: `tests/unit/test_booking_calendar_hybrid.py`

- [ ] **Step 1: Write failing tests** for hybrid logic (slot-doctor inline retry, token-doctor enqueue-only, fallback on inline fail).
  ```python
  # tests/unit/test_booking_calendar_hybrid.py
  from unittest.mock import AsyncMock, patch
  import pytest
  from backend.services.booking_calendar import write_booking_calendar
  from backend.services.calendar_service import CalendarWriteFailed
  
  @pytest.mark.asyncio
  async def test_token_doctor_enqueues_nothing(db, token_doctor_factory, token_factory):
      doctor = await token_doctor_factory()
      token = await token_factory(doctor=doctor)
      await write_booking_calendar(db, token, doctor, calendar_id=None)
      # No CalendarWriteTask row should exist
      from sqlalchemy import select
      from backend.models.schema import CalendarWriteTask
      rows = (await db.execute(select(CalendarWriteTask).where(CalendarWriteTask.token_id == token.id))).all()
      assert len(rows) == 0
  
  @pytest.mark.asyncio
  async def test_slot_doctor_sync_success(db, slot_doctor_factory, token_factory):
      doctor = await slot_doctor_factory()
      token = await token_factory(doctor=doctor)
      with patch("backend.services.booking_calendar.GoogleCalendarService") as mock_cls:
          mock_cls.return_value.create_booking_event = AsyncMock(return_value="evt_inline_123")
          await write_booking_calendar(db, token, doctor, calendar_id="cal_x")
      await db.refresh(token)
      assert token.google_calendar_event_id == "evt_inline_123"
  
  @pytest.mark.asyncio
  async def test_slot_doctor_sync_fail_falls_back_to_queue(db, slot_doctor_factory, token_factory):
      doctor = await slot_doctor_factory()
      token = await token_factory(doctor=doctor)
      with patch("backend.services.booking_calendar.GoogleCalendarService") as mock_cls:
          mock_cls.return_value.create_booking_event = AsyncMock(side_effect=CalendarWriteFailed("boom"))
          await write_booking_calendar(db, token, doctor, calendar_id="cal_x")
      from sqlalchemy import select
      from backend.models.schema import CalendarWriteTask
      rows = (await db.execute(select(CalendarWriteTask).where(CalendarWriteTask.token_id == token.id))).scalars().all()
      assert len(rows) == 1
      assert rows[0].status == "pending"
  ```

- [ ] **Step 2: Run — confirm FAIL**.

- [ ] **Step 3: Implement** `backend/services/booking_calendar.py`:
  ```python
  """Hybrid sync/async Calendar write per booking_type. See spec §6.7."""
  import asyncio
  from datetime import datetime
  from typing import Optional
  import structlog
  from backend.models.schema import Doctor, Token, CalendarWriteTask
  from backend.services.calendar_service import GoogleCalendarService, CalendarWriteFailed
  from backend.services.admin_alert import alert_admin
  
  logger = structlog.get_logger()
  SYNC_BACKOFF = [0, 2, 5]   # seconds between inline retries (slot-doctor only)
  
  
  async def _enqueue(db, token: Token, operation: str, payload: dict, status: str = "pending") -> None:
      db.add(CalendarWriteTask(
          branch_id=token.branch_id, token_id=token.id,
          operation=operation, payload_json=payload, status=status,
      ))
      await db.commit()
  
  
  def _build_payload(token: Token, doctor: Doctor, calendar_id: str, patient_first_name: str, patient_phone_last4: str) -> dict:
      dt = datetime.combine(token.date, token.appointment_time)
      return {
          "calendar_id": calendar_id,
          "patient_first_name": patient_first_name,
          "patient_phone_last4": patient_phone_last4,
          "appointment_dt": dt.isoformat(),
          "duration_minutes": doctor.slot_duration_minutes or 30,
          "doctor_name": doctor.name,
      }
  
  
  async def write_booking_calendar(
      db, token: Token, doctor: Doctor, calendar_id: Optional[str],
      patient_first_name: str = "", patient_phone_last4: str = "",
  ) -> None:
      if doctor.booking_type == "token":
          return  # token-doctor: no per-patient Cal event
  
      if not calendar_id:
          payload = _build_payload(token, doctor, "", patient_first_name, patient_phone_last4)
          await _enqueue(db, token, "create", payload, status="failed_permanent")
          await alert_admin("calendar_not_configured", token.branch_id, token.id)
          return
  
      payload = _build_payload(token, doctor, calendar_id, patient_first_name, patient_phone_last4)
      svc = GoogleCalendarService()
      last_err: Optional[Exception] = None
      for delay in SYNC_BACKOFF:
          if delay:
              await asyncio.sleep(delay)
          try:
              event_id = await svc.create_booking_event(
                  calendar_id=calendar_id,
                  patient_first_name=patient_first_name,
                  patient_phone_last4=patient_phone_last4,
                  appointment_dt=datetime.fromisoformat(payload["appointment_dt"]),
                  duration_minutes=payload["duration_minutes"],
                  doctor_name=doctor.name,
              )
              token.google_calendar_event_id = event_id
              await db.commit()
              return
          except CalendarWriteFailed as e:
              last_err = e
              logger.warning("calendar_sync_retry", attempt_delay=delay, error=str(e))
      # All inline attempts failed → fall back to async queue
      logger.error("calendar_sync_exhausted_enqueue", token_id=str(token.id), error=str(last_err))
      await _enqueue(db, token, "create", payload, status="pending")
      await alert_admin("calendar_sync_fail", token.branch_id, token.id)
  ```

- [ ] **Step 4: Run tests — confirm PASS**.

- [ ] **Step 5: Commit**
  ```bash
  git add backend/services/booking_calendar.py tests/unit/test_booking_calendar_hybrid.py
  git commit -m "feat(calendar): hybrid sync/async write helper (slot=sync inline retry, token=skip)"
  ```

---

## Task 7: RBAC tightening (security-engineer)

**Files:**
- Modify: `backend/middleware/branch_guard.py` (extend `assert_branch_access`)
- Modify: `backend/middleware/auth_middleware.py` (add `forbid_admin`)
- Test: `tests/security/test_rbac_super_admin_lockout.py` + `tests/security/test_rbac_org_admin_inheritance.py`

- [ ] **Step 1: Write failing tests**
  ```python
  # tests/security/test_rbac_super_admin_lockout.py
  import pytest
  from fastapi.testclient import TestClient
  
  @pytest.mark.asyncio
  async def test_super_admin_blocked_on_queue(super_admin_jwt, test_branch_id):
      client = TestClient(app)
      r = client.get(f"/queue/{test_branch_id}/today", headers={"Authorization": f"Bearer {super_admin_jwt}"})
      assert r.status_code == 403
      assert "use /admin" in r.json()["detail"].lower()
  
  @pytest.mark.asyncio
  async def test_super_admin_blocked_on_doctors(super_admin_jwt, test_branch_id):
      client = TestClient(app)
      r = client.get(f"/doctors/{test_branch_id}", headers={"Authorization": f"Bearer {super_admin_jwt}"})
      assert r.status_code == 403
  
  @pytest.mark.asyncio
  async def test_super_admin_allowed_on_admin_orgs(super_admin_jwt):
      client = TestClient(app)
      r = client.get("/admin/orgs", headers={"Authorization": f"Bearer {super_admin_jwt}"})
      assert r.status_code == 200
  ```
  ```python
  # tests/security/test_rbac_org_admin_inheritance.py
  @pytest.mark.asyncio
  async def test_org_admin_accesses_all_org_branches_without_branch_ids(db, org_admin_factory, branch_factory):
      org_id = "<uuid>"
      branch_a = await branch_factory(org_id=org_id)
      branch_b = await branch_factory(org_id=org_id)
      user_jwt = await org_admin_factory(org_id=org_id, branch_ids=[])  # NO branch_ids
      client = TestClient(app)
      assert client.get(f"/queue/{branch_a.id}/today", headers={"Authorization": f"Bearer {user_jwt}"}).status_code == 200
      assert client.get(f"/queue/{branch_b.id}/today", headers={"Authorization": f"Bearer {user_jwt}"}).status_code == 200
  
  @pytest.mark.asyncio
  async def test_org_admin_blocked_from_other_org_branch(db, org_admin_factory, branch_factory):
      branch_other = await branch_factory(org_id="<other-org-uuid>")
      user_jwt = await org_admin_factory(org_id="<my-org-uuid>")
      client = TestClient(app)
      assert client.get(f"/queue/{branch_other.id}/today", headers={"Authorization": f"Bearer {user_jwt}"}).status_code == 403
  ```

- [ ] **Step 2: Run — confirm FAIL**.

- [ ] **Step 3: Update `backend/middleware/branch_guard.py`** to enforce new rules:
  ```python
  from fastapi import HTTPException, Depends
  from backend.middleware.auth_middleware import get_current_user
  
  async def assert_branch_access(branch_id, user=Depends(get_current_user), db=Depends(get_db)):
      if user.role == "super_admin":
          raise HTTPException(403, "Platform admin cannot access clinic PII; use /admin endpoints")
      branch = await db.get(Branch, branch_id)
      if not branch:
          raise HTTPException(404, "branch not found")
      if user.role == "org_admin":
          if branch.org_id != user.org_id:
              raise HTTPException(403, "branch not in your org")
          return branch
      # receptionist + doctor
      if str(branch_id) not in (user.branch_ids or []):
          raise HTTPException(403, "branch not in your assignments")
      return branch
  ```

- [ ] **Step 4: Add `forbid_admin`** dep to `backend/middleware/auth_middleware.py`:
  ```python
  def forbid_admin(user=Depends(get_current_user)):
      if user.role == "super_admin":
          raise HTTPException(403, "Use /admin endpoints — platform admin cannot access clinic data")
      return user
  ```

- [ ] **Step 5: Run tests — confirm PASS**.

- [ ] **Step 6: Run full regression — no other test breakage**.

- [ ] **Step 7: Commit**
  ```bash
  git add backend/middleware/ tests/security/
  git commit -m "feat(security): super_admin locked OUT of clinic PII routes; org_admin auto-inherits org branches (DPDP)"
  ```

---

## Task 8: Doctors router (backend-engineer)

**Files:**
- Create: `backend/routers/doctors.py`
- Modify: `backend/main.py` (mount router)
- Test: `tests/integration/test_doctors_router.py`

- [ ] **Step 1: Write failing tests** for GET list, POST create with auto-defaults, PATCH update, DELETE soft, PATCH stop-walkins-today.
  ```python
  # tests/integration/test_doctors_router.py
  @pytest.mark.asyncio
  async def test_create_doctor_appointment_auto_defaults_followups_on(org_admin_jwt, test_branch_id):
      r = client.post(f"/doctors/{test_branch_id}", json={
          "name": "Dr Reddy", "booking_type": "appointment",
          "working_hours_start": "09:00", "working_hours_end": "17:00",
      }, headers=auth(org_admin_jwt))
      assert r.status_code == 201
      d = r.json()
      assert d["pre_appointment_reminder"] is True
      assert d["post_treatment_followup"] is True
  
  @pytest.mark.asyncio
  async def test_create_doctor_token_auto_defaults_followups_off(org_admin_jwt, test_branch_id):
      r = client.post(f"/doctors/{test_branch_id}", json={
          "name": "Dr Sharma", "booking_type": "token", "daily_token_limit": 10,
          "working_hours_start": "09:00", "working_hours_end": "13:00",
      }, headers=auth(org_admin_jwt))
      d = r.json()
      assert d["pre_appointment_reminder"] is False
      assert d["post_treatment_followup"] is False
  
  @pytest.mark.asyncio
  async def test_receptionist_cannot_create_doctor(receptionist_jwt, test_branch_id):
      r = client.post(f"/doctors/{test_branch_id}", json={"name": "X", "booking_type": "token"}, headers=auth(receptionist_jwt))
      assert r.status_code == 403
  
  @pytest.mark.asyncio
  async def test_stop_walkins_today(org_admin_jwt, test_branch_id, doctor_factory):
      doc = await doctor_factory(branch_id=test_branch_id)
      r = client.patch(f"/doctors/{test_branch_id}/{doc.id}/stop-walkins-today", headers=auth(org_admin_jwt))
      assert r.status_code == 200
      # next preflight should report walk-ins blocked
  ```

- [ ] **Step 2: Run — confirm FAIL**.

- [ ] **Step 3: Implement** `backend/routers/doctors.py`:
  ```python
  from datetime import date
  from typing import Optional
  from fastapi import APIRouter, Depends, HTTPException, status
  from pydantic import BaseModel
  from sqlalchemy import select
  from backend.database import get_db
  from backend.models.schema import Doctor, Branch
  from backend.middleware.branch_guard import assert_branch_access
  from backend.middleware.auth_middleware import require_role
  from backend.middleware.audit import audit
  from backend.services.calendar_service import GoogleCalendarService
  
  router = APIRouter(prefix="/doctors", tags=["doctors"])
  
  
  class DoctorIn(BaseModel):
      name: str
      specialization: Optional[str] = None
      booking_type: str  # 'token' | 'appointment'
      working_hours_start: Optional[str] = None  # "HH:MM"
      working_hours_end: Optional[str] = None
      available_weekdays: Optional[list[int]] = None
      slot_duration_minutes: Optional[int] = None
      max_concurrent_per_slot: Optional[int] = None
      daily_token_limit: Optional[int] = None
      pre_appointment_reminder: Optional[bool] = None
      post_treatment_followup: Optional[bool] = None
      invited_email: Optional[str] = None
      google_calendar_id: Optional[str] = None
  
  
  @router.get("/{branch_id}")
  async def list_doctors(branch=Depends(assert_branch_access), db=Depends(get_db)):
      result = await db.execute(select(Doctor).where(Doctor.branch_id == branch.id, Doctor.status == "active"))
      return [d.__dict__ for d in result.scalars().all()]  # cleaner DTO in real impl
  
  
  @router.post("/{branch_id}", status_code=201)
  @audit("doctor.create", resource_type="doctor")
  async def create_doctor(
      body: DoctorIn, branch=Depends(assert_branch_access),
      user=Depends(require_role("org_admin")), db=Depends(get_db),
  ):
      # Auto-defaults by booking_type
      pre_default  = (body.booking_type == "appointment")
      post_default = (body.booking_type == "appointment")
      doctor = Doctor(
          branch_id=branch.id,
          name=body.name, specialization=body.specialization,
          booking_type=body.booking_type,
          working_hours_start=body.working_hours_start,
          working_hours_end=body.working_hours_end,
          available_weekdays=body.available_weekdays or [0,1,2,3,4,5,6],
          slot_duration_minutes=body.slot_duration_minutes,
          max_concurrent_per_slot=body.max_concurrent_per_slot,
          daily_token_limit=body.daily_token_limit,
          pre_appointment_reminder=body.pre_appointment_reminder if body.pre_appointment_reminder is not None else pre_default,
          post_treatment_followup=body.post_treatment_followup if body.post_treatment_followup is not None else post_default,
          invited_email=body.invited_email,
          google_calendar_id=body.google_calendar_id,
      )
      db.add(doctor); await db.commit()
      # If token-doctor + cal_id set: upsert recurring hours event (best-effort)
      if doctor.booking_type == "token" and (doctor.google_calendar_id or branch.google_calendar_id):
          try:
              svc = GoogleCalendarService()
              eid = await svc.upsert_doctor_hours_event(
                  calendar_id=doctor.google_calendar_id or branch.google_calendar_id,
                  doctor_name=doctor.name,
                  working_hours_start=doctor.working_hours_start,
                  working_hours_end=doctor.working_hours_end,
                  available_weekdays=doctor.available_weekdays,
                  existing_event_id=None,
              )
              doctor.calendar_event_id_recurring = eid
              await db.commit()
          except Exception:
              pass  # best-effort; admin alerted via separate path
      return doctor.__dict__
  
  
  @router.patch("/{branch_id}/{doctor_id}")
  @audit("doctor.update", resource_type="doctor")
  async def update_doctor(
      doctor_id, body: DoctorIn, branch=Depends(assert_branch_access),
      user=Depends(require_role("org_admin")), db=Depends(get_db),
  ):
      doctor = await db.get(Doctor, doctor_id)
      if not doctor or doctor.branch_id != branch.id:
          raise HTTPException(404)
      # apply fields
      for field, value in body.model_dump(exclude_unset=True).items():
          setattr(doctor, field, value)
      await db.commit()
      # Sync recurring event for token-doctor if hours/weekdays changed
      if doctor.booking_type == "token" and (doctor.google_calendar_id or branch.google_calendar_id):
          try:
              svc = GoogleCalendarService()
              eid = await svc.upsert_doctor_hours_event(
                  calendar_id=doctor.google_calendar_id or branch.google_calendar_id,
                  doctor_name=doctor.name,
                  working_hours_start=doctor.working_hours_start,
                  working_hours_end=doctor.working_hours_end,
                  available_weekdays=doctor.available_weekdays,
                  existing_event_id=doctor.calendar_event_id_recurring,
              )
              doctor.calendar_event_id_recurring = eid
              await db.commit()
          except Exception:
              pass
      return doctor.__dict__
  
  
  @router.delete("/{branch_id}/{doctor_id}", status_code=204)
  @audit("doctor.delete", resource_type="doctor")
  async def soft_delete_doctor(
      doctor_id, branch=Depends(assert_branch_access),
      user=Depends(require_role("org_admin")), db=Depends(get_db),
  ):
      doctor = await db.get(Doctor, doctor_id)
      if not doctor or doctor.branch_id != branch.id:
          raise HTTPException(404)
      doctor.status = "inactive"
      await db.commit()
  
  
  @router.patch("/{branch_id}/{doctor_id}/stop-walkins-today")
  @audit("doctor.walkins_closed_today", resource_type="doctor")
  async def stop_walkins_today(
      doctor_id, branch=Depends(assert_branch_access), db=Depends(get_db),
  ):
      doctor = await db.get(Doctor, doctor_id)
      if not doctor or doctor.branch_id != branch.id:
          raise HTTPException(404)
      doctor.walkins_closed_today_date = date.today()
      await db.commit()
      return {"walkins_closed_today_date": doctor.walkins_closed_today_date.isoformat()}
  ```

- [ ] **Step 4: Mount in `backend/main.py`** `app.include_router(doctors.router)`.

- [ ] **Step 5: Run tests — confirm PASS**.

- [ ] **Step 6: Commit**
  ```bash
  git add backend/routers/doctors.py backend/main.py tests/integration/test_doctors_router.py
  git commit -m "feat(api): doctors CRUD with auto-defaults + recurring Cal event sync + stop-walkins-today"
  ```

---

## (Tasks 9–28 follow the same TDD pattern. Plan continues in next document section.)

> **Continuation note:** Tasks 9–28 (Availability, Walk-in, Followup, Branches, Doctor-self, Admin extensions, Warning scanner, RULE 4 amendment, PWA bootstrap, Auth, ServiceWorker, App shell, Queue page, Walk-in drawer, Doctors page, Unavailability drawer, Followup drawer, Admin dashboard, Doctor self-view, Acceptance gate) — each follows the same write-test-fail → implement → pass → commit cycle. They are continued in §B below to keep this document scannable.

---

# §B — Tasks 9–28

## Task 9: Availability router + cascade flow (backend-engineer)

**Files:** `backend/routers/availability.py` + `backend/services/cascade_cancel.py` + `tests/integration/test_availability_cascade.py`

- [ ] **Step 1: Write tests** for POST range (bulk insert + cascade cancel + followup_tasks insert + cal_write_tasks insert all in single tx), GET listing, DELETE, GET affected preflight.
- [ ] **Step 2: Implement `backend/services/cascade_cancel.py`** with `cascade_for_unavailability(db, branch_id, doctor_id, date_from, date_to, user_id)` returning `(unavailable_dates, cancelled_tokens, followups_scheduled)`. Single SQL transaction: insert into `doctor_unavailability` ON CONFLICT DO NOTHING; SELECT FOR UPDATE tokens in range; UPDATE status='cancelled_by_clinic'; INSERT followup_tasks task_type='cascade_rebook'; outside tx INSERT calendar_write_tasks delete-ops.
- [ ] **Step 3: Implement `backend/routers/availability.py`** with POST/GET/DELETE/affected endpoints.
- [ ] **Step 4: Mount + audit rows per cancelled token (`availability.cascade_cancel`)**.
- [ ] **Step 5: Run tests; commit `feat(api): availability + cascade cancel with followup + cal delete enqueue`**.

## Task 10: Walk-in router (backend-engineer)

**Files:** `backend/routers/walkin.py` + `backend/services/walkin_preflight.py` + `tests/integration/test_walkin_*.py`

- [ ] **Step 1: Write tests** for preflight blocks (unavailable / weekday / hours-over / cap-reached / walkins-closed-today), happy path token-doctor (Redis INCR), happy path slot-doctor (next free slot), over-cap rejection 422, emergency override path with `is_urgent=true` + `emergency_reason` + audit.
- [ ] **Step 2: Implement `walkin_preflight.can_walkin(db, redis, doctor, branch, now)`** returning `(allowed, reason, details)` per spec §8.
- [ ] **Step 3: Implement router**. POST → preflight check; on cap, return 422 with `override_path: "emergency"`; if `is_emergency=true` in body, require `emergency_reason`, bypass cap, set `Token.is_urgent=True`, audit `walkin.emergency_override`. Calls `write_booking_calendar` from Task 6 after Token committed.
- [ ] **Step 4: Mount + rate-limit `POST /walkin` to 30/min/user**.
- [ ] **Step 5: Commit `feat(api): walk-in with hard cap + emergency-only override + preflight`**.

## Task 11: Followup router (backend-engineer)

**Files:** `backend/routers/followup.py` + `tests/integration/test_followup_router.py`

- [ ] **Step 1: Tests** for POST create (consent gate: 422 if Patient.followup_consent=false), GET list by date, DELETE cancel.
- [ ] **Step 2: Implement** — POST body `{task_type='post_appt_check', scheduled_date, scheduled_at, what_to_ask, max_attempts=3}`; validates token_id belongs to branch; checks `patient.followup_consent` else 422.
- [ ] **Step 3: Commit `feat(api): followup task creation with consent gate`**.

## Task 12: Branches router — calendar config (backend-engineer)

**Files:** `backend/routers/branches.py` + `tests/integration/test_branches_calendar.py`

- [ ] **Step 1: Tests** for PATCH `/branches/{id}/calendar` with `{google_calendar_id}` — validates via probe (insert + delete test event); returns 400 if probe fails with explanatory message.
- [ ] **Step 2: Implement**. Probe pattern: insert event in past with `summary="vachanam probe"` → delete immediately. If 404 on calendar_id → return 400 "calendar not shared or invalid id".
- [ ] **Step 3: Commit `feat(api): branch calendar config with live probe validation`**.

## Task 13: Doctor self router (backend-engineer)

**Files:** `backend/routers/doctor_self.py` + `tests/integration/test_doctor_self.py`

- [ ] **Step 1: Tests** for GET `/doctor/me/queue?date=today` (must return only doctor's own patients), GET `/doctor/me/schedule`, GET `/doctor/me/followups`. Doctor role must NOT access other doctors' data; receptionist must NOT access `/doctor/me/*`.
- [ ] **Step 2: Implement** with `forbid_admin` dep + `require_role("doctor")` + DB query `WHERE doctor_id = (SELECT id FROM doctors WHERE user_id = user.id)`.
- [ ] **Step 3: Commit `feat(api): doctor self read-only routes`**.

## Task 14: Admin router extensions (backend-engineer)

**Files:** `backend/routers/admin.py` (extend) + `tests/integration/test_admin_extensions.py`

- [ ] **Step 1: Tests** for `/admin/lifetime-totals`, `/admin/warnings`, `/admin/pnl`, `/admin/orgs/{id}/usage`, `/admin/orgs/{id}/contacts`. Each test asserts DPDP-safe: no patient/doctor PII in any response.
- [ ] **Step 2: Implement** with aggregate SQL queries per spec §5.2 + §11.2 (COUNT/SUM only). PnL = revenue (sum BillingCycle paid) − costs (Vobiz minutes × rate + Sarvam minutes × rate + Gemini token estimate + fixed infra).
- [ ] **Step 3: Verify existing `/admin/orgs` + `/admin/orgs/{id}/branches`** don't leak `google_calendar_id` — strip if present.
- [ ] **Step 4: Commit `feat(api): admin lifetime totals + warnings + pnl + usage + contacts (DPDP-safe aggregates)`**.

## Task 15: Admin warning scanner job (backend-engineer)

**Files:** `backend/jobs/admin_warning_scanner.py` + `tests/unit/test_admin_warnings.py`

- [ ] **Step 1: Tests** for each warning type (overage approaching, trial expiring ≤3d, Cal broken ≥1 permanent fail, failed payment, churn signal = 0 inbound in 7d).
- [ ] **Step 2: Implement** as APScheduler hourly job. Writes to in-memory dict (or new `admin_warnings` table) consumed by `/admin/warnings`. Side-effect: email Vinay on new severe warnings (use `services/admin_alert.alert_admin` from Task 5).
- [ ] **Step 3: Wire into `backend/main.py` lifespan**. Commit `feat(jobs): admin warning scanner (hourly)`.

## Task 16: CLAUDE.md RULE 4 amendment + TD entries (main thread, NOT dispatched)

**Files:** `CLAUDE.md` + `docs/TECH_DEBT.md` + `docs/CHANGELOG.md`

- [ ] **Step 1: Edit CLAUDE.md RULE 4** — replace original block with new "DB write FIRST" rule per spec §4. Keep "WhatsApp deferred to MVP2" intact.
- [ ] **Step 2: Append TD-RULE4-CHANGE-2026-06-08** to `docs/TECH_DEBT.md` with original rule preserved + rationale + payback path.
- [ ] **Step 3: Append CHANGELOG entry** for 2026-06-09 sub-spec A merge.
- [ ] **Step 4: Commit `docs: amend RULE 4 (DB-first hybrid Cal write) + TD-RULE4-CHANGE entry`**.

## Task 17: PWA bootstrap (frontend-engineer)

**Files:** `frontend/package.json` + `frontend/vite.config.js` + `frontend/tailwind.config.js` + `frontend/postcss.config.js` + `frontend/index.html` + `frontend/src/main.jsx` + `frontend/src/App.jsx` + `frontend/public/manifest.json` + PWA icons (192, 512)

- [ ] **Step 1: `npm create vite@latest frontend -- --template react`**. Verify `npm run dev` opens default Vite page.
- [ ] **Step 2: Install deps**:
  ```bash
  cd frontend
  npm i react-router-dom @tanstack/react-query axios framer-motion sonner vaul \
        @hookform/resolvers zod date-fns date-fns-tz idb-keyval recharts
  npm i -D tailwindcss postcss autoprefixer vite-plugin-pwa workbox-window vitest @testing-library/react @testing-library/jest-dom playwright
  npx tailwindcss init -p
  ```
- [ ] **Step 3: Configure Tailwind** + Vite-PWA plugin in `vite.config.js`:
  ```js
  import { VitePWA } from 'vite-plugin-pwa';
  export default {
    plugins: [react(), VitePWA({
      registerType: 'autoUpdate',
      manifest: { name: 'Vachanam', short_name: 'Vachanam', start_url: '/', display: 'standalone' /* ... */ },
      workbox: { /* see Task 19 */ },
    })],
    server: { proxy: { '/api': 'http://localhost:8000' } },
  };
  ```
- [ ] **Step 4: Smoke test** `npm run dev` + `npm run build` clean.
- [ ] **Step 5: Commit `feat(frontend): Vite + React 18 + Tailwind + TanStack Query + PWA bootstrap`**.

## Task 18: Auth bootstrap (frontend-engineer)

**Files:** `frontend/src/api/client.js` + `frontend/src/hooks/useAuth.js` + `frontend/src/pages/Login.jsx` + IndexedDB persistence + axios interceptor

- [ ] **Step 1: Vitest test** for axios interceptor adds `Authorization: Bearer <jwt>` + on 401 wipes JWT + redirects `/login`.
- [ ] **Step 2: Implement** axios client wrapper using `idb-keyval` for JWT persistence. `useAuth()` hook exposes `{ jwt, user, branchIds, isAdmin, login, logout }`.
- [ ] **Step 3: Login page** with Google Sign-In button → `POST /auth/google` → store JWT → redirect by role.
- [ ] **Step 4: Commit `feat(frontend): Google auth + JWT in IndexedDB + axios interceptor`**.

## Task 19: Service worker + Workbox + offline plumbing (frontend-engineer)

**Files:** `frontend/vite.config.js` workbox section + `frontend/src/api/mutationQueue.js`

- [ ] **Step 1: Vitest test** for `mutationProxy(req)` — on `fetch.reject`, enqueues to IndexedDB; on `navigator.online`, drains queue oldest-first.
- [ ] **Step 2: Configure Workbox runtime caching** per spec §10 (NetworkFirst for `/queue/*`, StaleWhileRevalidate for `/doctors/*`, NetworkOnly for `/walkin/*` + `/admin/*`).
- [ ] **Step 3: BackgroundSync** queue for POST `/followup`, PATCH `/queue/*/attend|no-show`, PATCH `/doctors/*`, POST `/availability` (NOT walk-in or cascade — those blocked offline).
- [ ] **Step 4: Sonner toast bindings** — "Saved offline / Synced / Sync failed".
- [ ] **Step 5: Commit `feat(frontend): Workbox SW + IndexedDB mutation queue + BackgroundSync`**.

## Task 20: App shell + routing + role-based nav (frontend-engineer)

**Files:** `frontend/src/App.jsx` + `frontend/src/components/Nav.jsx` + `frontend/src/components/BranchSwitcher.jsx` + `frontend/src/components/ErrorBoundary.jsx`

- [ ] **Step 1: Vitest test** that nav items differ per role (receptionist sees Queue/Walk-in/Doctors-read/Followups; org_admin adds Dashboard; doctor sees Me/Schedule; super_admin sees Admin only).
- [ ] **Step 2: Implement** routes per spec §7.2 with React Router v6. Lazy-load Doctor/Admin/Followup pages.
- [ ] **Step 3: 3-layer error boundary** (root → route → query). Root logs to `/client-errors` POST.
- [ ] **Step 4: Branch switcher visible when `user.branchIds.length > 1`**.
- [ ] **Step 5: Commit `feat(frontend): app shell + role-based nav + error boundaries`**.

## Task 21: Queue page (frontend-engineer)

**Files:** `frontend/src/pages/Queue.jsx` + `frontend/src/components/PatientCard.jsx` + `frontend/src/hooks/useQueue.js` + `frontend/src/hooks/useMarkAttendance.js`

- [ ] **Step 1: Playwright E2E test** scenario: receptionist logs in → sees today's queue → taps Attended on Token #8 → card slides to "attended" section via Framer Motion + Sonner toast appears.
- [ ] **Step 2: Implement Queue.jsx** matching Section 5 mockup: hero "N remaining" number + per-doctor section + voice/walk-in/emergency card variants (orange/red border) + collapsed "attended today" details.
- [ ] **Step 3: useQueue hook** with TanStack Query + 30s polling + 52px tap targets in PatientCard.
- [ ] **Step 4: useMarkAttendance optimistic mutation** — updates query cache immediately, queues on offline fail.
- [ ] **Step 5: Commit `feat(frontend): Queue page with optimistic attendance + Framer Motion reorder + Sonner toasts`**.

## Task 22: Walk-in drawer + adaptive form + preflight (frontend-engineer)

**Files:** `frontend/src/components/WalkInDrawer.jsx` + `frontend/src/hooks/useWalkInPreflight.js`

- [ ] **Step 1: Playwright E2E test** for: token-doctor walk-in success; slot-doctor walk-in with slot picker; over-cap rejection screen; emergency override path with reason validation.
- [ ] **Step 2: Implement Vaul bottom-sheet drawer** with form (name, optional phone, doctor select). Pre-flight on doctor change via `useWalkInPreflight(branchId, doctorId)` → renders adaptive UI: token mode = confirm button only; slot mode = slot picker with N/max occupancy chips.
- [ ] **Step 3: 422 over-cap response** → swap form to rejection card with "Mark as EMERGENCY" checkbox + reason textarea (required). Resubmit with `is_emergency=true` + `emergency_reason`.
- [ ] **Step 4: Phone-empty warning** yellow inline note (not blocking).
- [ ] **Step 5: Commit `feat(frontend): walk-in drawer with adaptive form + preflight + emergency override`**.

## Task 23: Doctors list + edit page (frontend-engineer)

**Files:** `frontend/src/pages/Doctors.jsx` + `frontend/src/pages/DoctorEdit.jsx` + `frontend/src/hooks/useDoctors.js`

- [ ] **Step 1: Playwright E2E test** — org_admin creates doctor (booking_type=appointment) → asserts followup toggle defaults to ON → toggles weekday chips → debounced save → Sonner success.
- [ ] **Step 2: Implement list** (`/doctors`) + edit (`/doctors/:id`) per Section 3 mockup: name, specialization, booking_type toggle, weekday picker (7 chips with Tailwind active/inactive states), working hours range, daily_token_limit (token mode only), max_concurrent_per_slot (slot mode only), reminders toggles, invited Google email, Google Cal id with "Test connection" button.
- [ ] **Step 3: Debounced PATCH** (500ms after last change). Display existing unavailability list (read-only here; mark-unavailable drawer in Task 24).
- [ ] **Step 4: Commit `feat(frontend): doctors list + edit with debounced auto-save + weekday picker`**.

## Task 24: Doctor unavailability drawer (frontend-engineer)

**Files:** `frontend/src/components/UnavailabilityDrawer.jsx` + `frontend/src/hooks/useAffectedTokens.js`

- [ ] **Step 1: Playwright E2E test** — org_admin opens drawer → picks date range → drawer shows "8 patients booked" → confirms → Sonner toast "8 patients will be called to reschedule".
- [ ] **Step 2: Implement Vaul drawer** with from/to date pickers + reason textarea. On range change, debounce-call `/availability/{branch}/{doctor}/affected?from=&to=` → display affected token list (anonymized: "Token #3 · 02 Jul · 10:30am"; receptionist sees first name + last 4 since they have branch access, doctor self-view masks).
- [ ] **Step 3: Confirm button** disabled until both dates picked. On confirm, POST `/availability/...` → close drawer + show Sonner success.
- [ ] **Step 4: Commit `feat(frontend): doctor unavailability drawer with cascade preview`**.

## Task 25: Followup drawer (frontend-engineer)

**Files:** `frontend/src/components/FollowupDrawer.jsx`

- [ ] **Step 1: Playwright E2E test** — receptionist marks slot-doctor patient attended → followup drawer auto-opens for appointment-doctor (or button visible for token-doctor with post_treatment_followup=true); fills "what to ask"; POST `/followup/{branch}/token/{token_id}`; drawer closes; Sonner confirms.
- [ ] **Step 2: Drawer gating** — render only when `doctor.post_treatment_followup === true`. Hide button entirely otherwise.
- [ ] **Step 3: Consent gate** — if `patient.followup_consent === false`, show "Patient declined consent" + disable submit.
- [ ] **Step 4: Commit `feat(frontend): followup drawer with consent gate + booking_type gating`**.

## Task 26: Admin dashboard Layout A (frontend-engineer)

**Files:** `frontend/src/pages/AdminDashboard.jsx` + `frontend/src/components/admin/KpiStrip.jsx` + `frontend/src/components/admin/WarningsList.jsx` + `frontend/src/components/admin/ClinicsTable.jsx` + `frontend/src/components/admin/CostBreakdown.jsx` + `frontend/src/hooks/useCountUp.js`

- [ ] **Step 1: Playwright E2E test** — super_admin loads `/admin` → 2 KPI strips render with count-up animation → warnings list shows 3 items → clinics table renders 6 rows → click row opens slide-right detail panel.
- [ ] **Step 2: Implement Layout A** per Section 5 final mockup: top KPI strip (Revenue MTD / Profit MTD / Margin / Active clinics / Trials in 3d), bottom strip (Patients booked / Calls handled / Minutes used / Branches live). Both use `useCountUp` for number animation.
- [ ] **Step 3: Warnings list** with severity icons (🟠/🔴), action buttons ("Notify clinic").
- [ ] **Step 4: Usage trend chart** (Recharts line), revenue-by-plan summary, clinics table with click-to-drill side panel.
- [ ] **Step 5: Cost breakdown** as final card with monospace currency.
- [ ] **Step 6: Keyboard shortcuts** (`c`/`w`/`?`) per spec §7.9.
- [ ] **Step 7: 60s polling** via TanStack Query.
- [ ] **Step 8: Commit `feat(frontend): Admin dashboard Layout A (Mission Control) with KPI count-up + warnings + drill`**.

## Task 27: Doctor self view (frontend-engineer)

**Files:** `frontend/src/pages/Me.jsx`

- [ ] **Step 1: Playwright E2E test** — doctor logs in → sees own queue (read-only attended/no-show buttons hidden) → sees schedule + upcoming unavailability.
- [ ] **Step 2: Implement** using `/doctor/me/*` endpoints. Reuse PatientCard component with `readOnly` prop.
- [ ] **Step 3: Commit `feat(frontend): doctor self read-only view`**.

## Task 28: Acceptance gate + sprint close (tester + manager)

**Dispatch:** tester first to run full acceptance criteria; manager to close sprint after tester signs off.

- [ ] **Step 1: tester** runs every checkbox in spec §11.2. Refuses to sign off if any criterion fails. Reports red/green per item.
- [ ] **Step 2: Fix any red items** by re-dispatching the appropriate task's owning agent.
- [ ] **Step 3: manager** appends TD entries (TD-WALKIN-CAP, TD-CAL-UNAVAIL-SYNC, TD-DPDP-ADMIN-DBROLE, TD-ADMIN-AUDIT-EXISTING per spec) to `docs/TECH_DEBT.md`.
- [ ] **Step 4: manager** updates `docs/STATUS.md` + `docs/CHANGELOG.md` + project memory.
- [ ] **Step 5: Final commit `chore(sprint): close sub-spec A — Calendar + PWA + Admin shipped`**.

---

## Self-review (against spec)

Spec coverage check:
- §3 schema → Task 2 ✓
- §4 RULE 4 amendment → Task 16 ✓
- §5 backend endpoints → Tasks 8/9/10/11/12/13/14 ✓
- §6 Calendar service → Tasks 3/4/5/6 ✓
- §7 PWA architecture → Tasks 17/18/19/20 ✓
- §8 walk-in timing → Task 10 ✓
- §9 cascade flow → Task 9 ✓
- §10 Workbox strategies → Task 19 ✓
- §11 tests + acceptance → embedded per task + Task 28 final gate ✓
- §15 pre-flight → Task 1 ✓
- RBAC tightening → Task 7 ✓
- Admin dashboard → Task 26 ✓
- Each UX page (Queue/Walk-in/Doctor edit/Unavail/Followup/Admin/Me) → Tasks 21/22/23/24/25/26/27 ✓

Placeholder scan: no TBD/TODO. Brief skeletons for Tasks 9-15 + 17-28 are intentional — each contains test scope + implementation scope + commit message; the implementing subagent has the spec for full detail. If reviewer prefers full code per task, expand inline.

Type consistency: `CalendarWriteTask.token_id` referenced in Tasks 5/6/9 — all consistent. `Doctor.available_weekdays` JSONB[int] used in Tasks 2/4/8/23 — consistent. `FollowupTask.task_type` values consistent across Tasks 2/9/11.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-06-08-calendar-and-receptionist-pwa-plan.md`.

Per CLAUDE.md mandate: use **subagent-driven-development**. Main thread dispatches each task to its named agent, runs two-stage review (spec-compliance → code-quality) between tasks, marks TodoWrite complete, moves on.

Vinay's pre-flight (Task 1) must complete before Task 2.
