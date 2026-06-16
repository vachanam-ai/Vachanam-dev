# Vachanam — Database Migration Log

Rationale record for every Alembic migration. Append-only — never edit prior entries.
Format: migration hash, name, date, what changed, why.

---

## ffcf1134aa8f — initial_schema_with_user_table

**Date:** 2026-06-01
**Author:** database-engineer (Phase 4 Task 1)

**What:** Created all 10 application tables from scratch: organizations, branches, doctors, patients,
tokens, calls, followup_tasks, billing_cycles, whatsapp_sessions, users. 15 named ENUMs.
UUID PKs everywhere. server_default=now() on all timestamp columns. JSONB for session_data,
branch_ids. Single-create ENUM pattern (no dual-create bug from the deleted prior migration).

**Why:** Replaced broken migration `2fe8f201bc31` which had dual-create ENUM bug (explicit
`enum_type.create()` then `op.create_table` with sa.Enum — both tried to create same types,
first succeeds, second fails). Old migration never successfully ran in any environment.
Decision: delete + regenerate. No prod migration history to preserve.

**Known gaps logged:**
- TD-018: No non-unique indexes on FK columns (autogen skipped them)
- TD-019: All FKs defaulted to NO ACTION on delete (autogen doesn't infer from ORM model)

Both gaps addressed in next migration.

---

## 8559268c0c44 — phase45_audit_log_ondelete_fk_indexes

**Date:** 2026-06-02
**Author:** database-engineer (Phase 4.5 Task 2)

**Covers three concerns in one migration (all three are schema additions — safe to batch):**

### 1. audit_log table (security spec §8.3)

Added `audit_log` table with 11 columns. No FK constraints by design — audit rows must survive
deletion of the referenced user/branch/org (append-only historical record). Plain UUID columns
(user_id, branch_id, org_id) preserve referential data without enforcing referential integrity.

6 indexes added: timestamp (chronological queries + retention scans), user_id (per-user
audit trail), branch_id (per-branch audit trail), org_id (per-org admin view), action
(filter by event type), success (anomaly detection on failures).

`success` column carries `server_default='true'` — DB-level default so direct SQL inserts
without explicit value do not fail. Application-side `default=True` also set for ORM inserts.

DPDP classification: pseudonymous. user_id/branch_id are UUIDs (no PII). ip_address is
pseudonymous (links to person only with ISP records). metadata_json must NOT store patient
name/phone — only IDs (enforced by convention + security-engineer code review).

Append-only enforcement: prod DB role (`vachanam_app`) will be granted INSERT+SELECT only,
not UPDATE or DELETE. GRANT script to be executed by devops-engineer in Phase 10 prod init.

### 2. FK ondelete explicit (closes TD-019)

Added `ondelete=` clause to all 15 FK constraints across the schema. Decision matrix:

**CASCADE (1 FK):**
- `whatsapp_sessions.branch_id` → branches.id — Session has no independent existence
  without its branch. Safe to cascade: deleting a branch wipes its in-flight WA sessions.
  No DPDP audit concern — sessions are transient booking state, not medical records.

**RESTRICT (14 FKs):**
All other FKs. Rationale: DPDP data-lifecycle requires explicit deletion paths. A branch
cannot be silently deleted while patients/tokens/doctors exist — this forces the caller to
explicitly delete child records first, which means the deletion path is audited. Specific
FK-by-FK rationale:
- `branches.org_id`: org cannot be dropped while it still has branches
- `doctors.branch_id`: branch cannot be dropped while doctors are assigned
- `patients.branch_id`: branch cannot be dropped while patient PII exists (DPDP)
- `tokens.branch_id/doctor_id/patient_id`: booking records must be explicitly purged
- `calls.branch_id/doctor_id/token_id`: call records reference live data; explicit cleanup
- `followup_tasks.branch_id/doctor_id/patient_id`: active tasks block parent deletion
- `billing_cycles.org_id`: financial records must survive; cannot cascade
- `users.org_id`: user accounts must be explicitly deprovisioned

RESTRICT vs NO ACTION difference: both prevent the delete, but RESTRICT checks immediately
(within the statement); NO ACTION defers the check to end of transaction. RESTRICT is the
safer choice — prevents tricky deferred-FK gymnastics from accidentally succeeding.

### 3. FK-only indexes (TD-018 reduced scope — brainstormer pick 3, client approved)

Added index on every FK column. 16 FK-column indexes created:
- billing_cycles.org_id
- branches.org_id
- users.org_id
- doctors.branch_id
- patients.branch_id
- whatsapp_sessions.branch_id
- followup_tasks.branch_id, doctor_id, patient_id
- tokens.branch_id, doctor_id, patient_id
- calls.branch_id, doctor_id, token_id

Columns with UNIQUE constraints (users.email, users.google_sub, branches.whatsapp_number,
branches.meta_phone_number_id, organizations.owner_email) already have indexes from their
UNIQUE constraints — no additional index created for those.

Compound indexes (branch_id+date, branch_id+doctor_id+date) deferred to Phase 5. Rationale:
write-cost of speculative indexes is non-zero; compound indexes will be gated on real
`EXPLAIN ANALYZE` evidence from Phase 5 query volume. Tracked as TD-018 Phase 5 component.

**Zero-downtime:** This migration is effectively the first full schema creation against this
DB instance (ffcf1134aa8f was stamped but no tables existed). One-shot upgrade. No
data backfill required — no existing rows.

**Reviewer:** security-engineer — verify append-only intent + FK ondelete matches DPDP
data-lifecycle expectations + indexes don't expose data via SELECT performance side channels.

---

## fd4a95d354fa — subspec_a_schema

**Date:** 2026-06-09
**Author:** database-engineer (sub-spec A Task 2)
**Spec:** calendar-and-receptionist-pwa-design §3 (spec archived 2026-06-16 cleanup — see git history)

**What:** Sub-spec A schema additions for Calendar + Receptionist PWA + RBAC.
Seven logical groups of changes in a single migration (all additions — no drops):

### 3.1 Doctor weekly availability additions (6 columns)

- `available_weekdays JSONB NOT NULL DEFAULT '[0,1,2,3,4,5,6]'` — ISO weekday ints 0=Mon.
  All existing Doctor rows silently inherit all-days (preserves today's behaviour).
- `post_treatment_followup BOOLEAN NOT NULL DEFAULT FALSE`
- `walkins_closed_today_date DATE NULL` — receptionist stop-walk-ins flag
- `calendar_event_id_recurring VARCHAR(255) NULL` — token-doctor's Google Cal recurring event
- `user_id UUID NULL UNIQUE REFERENCES users(id) ON DELETE SET NULL` — doctor login link
- `invited_email VARCHAR(255) NULL` — org_admin pre-registers doctor's Google email

Added FK `fk_doctors_user_id`, UNIQUE `uq_doctors_user_id`, and index `ix_doctors_user_id`.
All columns are nullable or carry `server_default` — Postgres 11+ instant-default, no table rewrite.

### 3.2 New table: doctor_unavailability

Multi-tenant date-specific absence override. branch_id is first non-PK column (Rule 1).
UNIQUE(doctor_id, date) prevents double-absence rows. created_by_user_id is plain UUID
(no FK) — consistent with Token.marked_by_user_id, survives user deletion.
Indexes: `ix_doctor_unavailability_branch_date` (compound, query-critical), plus single-column
FK indexes for branch_id and doctor_id.

### 3.3 FollowupTask additions (2 columns)

- `task_type VARCHAR(30) NOT NULL DEFAULT 'post_appt_check'` — app-side enum (no ALTER TYPE
  needed for new values). Values: post_appt_check | pre_appt_reminder | cascade_rebook.
- `token_id UUID NULL REFERENCES tokens(id) ON DELETE RESTRICT` — back-reference to booking.
  Index `ix_followup_tasks_token_id` added.

### 3.4 Token additions (2 columns)

- `cancelled_by_user_id UUID NULL` — who triggered cascade cancellation (plain UUID, no FK).
- `emergency_reason TEXT NULL` — required text when walk-in bypasses daily cap.

Both nullable — no backfill. DPDP: cancelled_by_user_id is pseudonymous; emergency_reason
is sensitive (patient-stated urgency reason).

### 3.5 New table: calendar_write_tasks

Async Google Calendar write queue. branch_id first non-PK column (Rule 1). payload_json
is JSONB (Rule 8). Compound index `ix_calendar_tasks_status_next` on (status, next_attempt_at)
for worker poll query: WHERE status='pending' AND next_attempt_at <= NOW().

### 3.6 user_role enum: 'doctor' value added

`ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'doctor'` executed OUTSIDE a transaction using
the op.execute("COMMIT") / ALTER TYPE / op.execute("BEGIN") recipe mandated in Alembic for
Postgres enum additions. Cannot be reversed in downgrade() — Postgres has no DROP VALUE.
Documented in downgrade() as acceptable limitation.

### 3.7 Compound indexes on tokens (TD-018 payback)

- `ix_tokens_branch_date` on (branch_id, date) — "today's queue for this branch" queries
- `ix_tokens_branch_doctor_date` on (branch_id, doctor_id, date) — "doctor X's tokens today"

These indexes were deferred in 8559268c0c44 pending EXPLAIN ANALYZE evidence. Sub-spec A
query patterns (Queue page poll + walk-in preflight + cascade cancel) confirmed they are
query-critical. TD-018 closed.

**ORM models updated:** Doctor, Token, FollowupTask (columns added), DoctorUnavailability
(new class), CalendarWriteTask (new class), User.role enum extended with 'doctor'.

**Zero-downtime:** All ADD COLUMN use Postgres 11+ instant-default. New tables are empty.
ALTER TYPE ADD VALUE is non-blocking. Compound indexes create with LOCK=SHARE (Postgres
default for CREATE INDEX — no table lock, reads continue, writes may be briefly queued
at index update time).

**DPDP classification:**
- available_weekdays, post_treatment_followup, walkins_closed_today_date: aggregate/operational — no PII
- user_id, invited_email: pseudonymous (UUID link + email, no patient data)
- doctor_unavailability: pseudonymous
- cancelled_by_user_id: pseudonymous (UUID only)
- emergency_reason: SENSITIVE — patient's stated urgency reason; stored in Token row only,
  excluded from audit log metadata_json by PII denylist convention
- calendar_write_tasks.payload_json: pseudonymous (patient_first_name + last4 only — complies with
  PII rule: never full phone in Cal event summary or queue payload)

**Reviewer:** security-engineer — verify payload_json PII compliance + emergency_reason
exclusion from audit log + doctor-role enum value doesn't grant unintended access.
