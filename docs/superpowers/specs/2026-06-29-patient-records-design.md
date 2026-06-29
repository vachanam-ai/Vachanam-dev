# Patient Records: Dedup + Patient Information View + Greet-by-Name — Design

**Date:** 2026-06-29
**Author:** Vinay (requirements) + agent (design)
**Status:** approved (pending spec review)

## Goal

Make patient records precise and de-duplicated, give clinics an editable
**Patient Information** view, and have the agent greet returning callers by name
and book efficiently for them (asking self-vs-other so it only collects details
when needed).

## Constraints (project)

- RULE 1 tenant isolation: every query/route branch-scoped; super_admin denied on
  clinic-PII routes.
- RULE 9 PII discipline: name/age/phone are PII — patient-info routes are clinic
  (org_admin/staff) only; no PII in logs.
- Telugu agent lines via Gemini spoken-gen (never hand-written), Vinay reviews.
- Additive Alembic migration forward from head.

## 1. Data model + de-duplication

**Rule:** within a branch, no two patients may share the same phone AND name
(case-insensitive). A phone can still have MULTIPLE patients (family), but each
must have a DISTINCT name. One patient per phone is the **primary** (the owner).

**Schema (`backend/models/schema.py`, `Patient`):**
- Add `is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)`.
- Add a partial unique index (case-insensitive name, only when phone present):
  `Index("uq_patient_branch_phone_name", "branch_id", "phone", func.lower(Patient.name), unique=True, postgresql_where=text("phone IS NOT NULL"))`.

**Migration (`alembic/versions/<id>_patient_dedup.py`, additive):**
1. Add `is_primary` column (default false).
2. **Merge existing duplicates** (same branch_id, phone, lower(name)): keep the
   earliest-`created_at` row as canonical; for each duplicate, repoint
   `tokens.patient_id`, `treatment_notes.patient_id`, `followup_tasks.patient_id`
   to the canonical id, then delete the duplicate. (Order matters — repoint all
   FKs before delete. This cleans the current test rows.)
3. Set `is_primary = TRUE` for exactly one patient per (branch_id, phone): the
   earliest-`created_at` row. (NULL-phone rows: each is its own primary = TRUE.)
4. Create the partial unique index.
- `downgrade()`: drop the index + the column (no un-merge — irreversible data
  cleanup, noted in the migration docstring).

**find-or-create (callers):** `assign_token`/`confirm_booking`
(`backend/services/booking_calendar.py`) and the walk-in desk
(`backend/routers/queue.py`) already match on phone+name; change the match to
**case-insensitive** (`func.lower(Patient.name) == wanted.lower()`), reuse on
hit, else create. When creating the FIRST patient on a phone (no existing
patient with that phone in the branch), set `is_primary=True`; otherwise
`is_primary=False`. The DB unique index is the backstop against races.

## 2. Patient Information view

**Backend (`backend/routers/patients.py`, new router, `forbid_admin`):**
- `GET /patients/branches/{branch_id}/patients` → `assert_branch_access`; returns
  `{patients: [{id, name, age, phone, is_primary, last_doctor}]}` sorted by name.
  `last_doctor` = the doctor on the patient's most-recent `Token` (by date desc,
  then created_at desc); null if none. One batched query for the latest token per
  patient (avoid N+1).
- `PATCH /patients/{patient_id}` → body `{branch_id, name?, age?, phone?}`.
  `assert_branch_access`; load the patient (404 if not in branch). Apply changes;
  if name or phone changed, check no OTHER patient in the branch has the same
  (phone, lower(name)) → else **409** `{detail: "duplicate_patient"}`. Commit.
  Re-evaluate `is_primary` if the phone changed (a moved-to-new-phone patient
  becomes primary of the new phone if it has none).
- Validation: age 0–120 or null; phone via `normalize_indian_phone` when present
  (null allowed); name non-empty, ≤255.

**Frontend (`frontend/src/pages/Patients.jsx` + `api/patients.js` + nav link):**
- New **Patients** nav entry (clinic owner/staff). Table: Name · Age · Phone ·
  Last doctor · (primary chip). Inline edit (name/age/phone) with a Save per row;
  `PATCH` on save. 409 → toast "Another patient already has this name + number".
  TanStack Query; invalidate on save. Mobile-first, matches existing pages.

## 3. Greet-by-name + known-caller booking

**Primary-aware recognition (`agent/tools/booking_tools.py`):**
- `recognize_caller_name`: when several patients share the phone, return the
  **`is_primary`** patient's name (instead of None). Still branch-scoped. None
  only when no patient / no primary on file.

**Booking flow (`agent/prompts/system_prompt.py`) — KNOWN caller (recognized):**
- Greet by name (existing live `known_caller_greeting`).
- After the patient states the issue, ask ONCE: "ఈ అపాయింట్‌మెంట్ మీకేనా, లేక వేరే
  వాళ్లకా?" (is this for you, or someone else?). [Gemini-generated final wording.]
  - **For themselves** → do NOT ask name/age (use the caller's own record). Take
    only the issue (→ route to doctor) + preferred time, then book under the
    caller's patient (their phone, is_primary). confirm_booking with the known
    name, `different_person=false`.
  - **Someone else** → take the patient's **name** + **age**, and an **OPTIONAL**
    phone (the agent must NOT insist on a phone — STT mishears spoken digits; if
    not given, book under the caller's phone with the new name). confirm_booking
    with that name + age, `different_person=true` → creates/reuses a family-member
    record (same phone, distinct name, is_primary=false).
- "Every 2nd call" = the patient already has a record → recognized → greeted by
  name. First call creates the record; subsequent calls greet.

**Unknown caller** (no record): unchanged new-patient flow (collect name/age).

## Out of scope
- Merging patients in the UI (only the one-time migration merge).
- Editing `is_primary` from the UI (system-managed).
- WhatsApp/notifications (MVP2).

## Testing
- Migration: seed duplicate patients + their tokens/notes/tasks → run upgrade →
  assert one canonical patient, FKs repointed, one is_primary per phone, index
  present; a second insert of the same phone+name raises IntegrityError.
- find-or-create: same phone+name (different case) reuses one row; same phone +
  new name creates a second (is_primary=false).
- `PATCH /patients`: edit name/age ok; phone edit colliding → 409; cross-branch
  patient → 404; super_admin → 403.
- `GET /patients`: returns last_doctor correctly; branch-scoped.
- recognize_caller_name: multi-name phone → returns the primary's name.
- Agent: sims — known caller self → no name/age asked; "someone else" → name+age
  asked, phone optional.
- Full suite green; `npm run build` clean. FIXLOG row per change.
