# Sub-spec A — Google Calendar Real Impl + Receptionist PWA + Admin Dashboard

**Date:** 2026-06-08
**Author:** Vinay Rongala (architect: Claude main thread)
**Status:** DRAFT — awaiting Vinay review before plan
**Sprint:** Vachanam MVP1 post-Pipecat — sub-spec A of 4 (A, B, C, D)
**Prereqs:** Phase 1 (Pipecat inbound) deployed; Phase 4 backend live; Phase 4.5 security live.
**Blocks:** Sub-specs B (outbound voice infra), C (pre-appt + post-appt + cascade voice), D (onboarding + DID + dashboards UI).

---

## 0. Why this exists

Vachanam ships in 4 sub-specs after the Pipecat sprint closed (2026-06-08). Sub-spec A is the lowest-infra-risk, demo-unblocking foundation:

- Replaces the Google Calendar stub with a real implementation.
- Bootstraps the Receptionist Progressive Web App (PWA) — queue, walk-in, doctor edit, follow-up creation, admin dashboard.
- Adds schema needed for date-specific doctor availability + cascade cancellation + follow-up task typing.
- Wires role-based access control so org owners + receptionists + doctors see only what DPDP allows them to see.
- Locks platform-admin (Vinay) RBAC so Vachanam-side cannot access clinic patient PII.

Sub-spec A produces nothing that requires outbound voice. All voice work — pre-appt reminders, post-treatment follow-up calls, cascade-rebook calls — sits behind sub-spec B + C and consumes data this sub-spec writes (FollowupTask rows).

---

## 1. Verified external facts (no assumptions)

Verified 2026-06-08 via parallel research subagents. Source URLs in `docs/superpowers/specs/2026-06-08-verifications.md` (to be created during plan execution).

| Item | Status | Decision |
|---|---|---|
| Google Calendar service account + per-clinic share | VERIFIED — works for personal Gmail + Workspace; no App Verification needed for service-account flow | Use Option A |
| Calendar API free tier | VERIFIED — 1M calls/day, our scale ≤ 0.3% of quota | No paid tier needed |
| Secrets storage on Render | VERIFIED — base64-encode SA JSON, store as env, decode at boot to `/tmp/google-sa.json` | Lock this pattern |
| Vobiz outbound make_call | VERIFIED endpoint (`POST /Account/{auth_id}/Call/`) + flow (provider dials → answer_url) | Used in sub-spec B/C, not here |
| Vobiz Voice Application provisioning API | UNVERIFIED — endpoint indexed but schema undocumented | Goes to Vobiz support; sub-spec D scope |
| Pipecat outbound dial pattern | VERIFIED — provider dials, Pipecat answers like inbound. Per-call context via `answer_url?task_id=X` | Used in sub-spec B, not here |

---

## 2. Scope

### IN scope for sub-spec A
- Real Google Calendar service replacing both stub files (`agent/services/calendar_stub.py` + `backend/services/calendar_service.py`).
- Hybrid calendar write strategy: sync inline for appointment-type doctors, async queue for token-type.
- Calendar write retry queue (`calendar_write_tasks` table + APScheduler worker).
- Doctor weekly availability (Doctor.available_weekdays JSONB) + date-specific override (`doctor_unavailability` table).
- Cascade cancellation flow (mark doctor unavailable → bulk cancel tokens → enqueue FollowupTasks of type `cascade_rebook` for sub-spec C).
- Walk-in registration endpoint + hard-cap + emergency override.
- Follow-up scheduling endpoint (creates FollowupTask rows; consumption is sub-spec C).
- PWA bootstrap: React 18 + Vite 5 + Tailwind 3 + TanStack Query + Workbox + axios + Framer Motion + Sonner + Vaul + idb-keyval + zod.
- PWA pages: Login, Queue, Walk-in, Doctors list + edit, Doctor unavailability drawer, Follow-up scheduling drawer, Admin dashboard (Layout A — Mission Control), Doctor self-view (read-only).
- RBAC tightening: super_admin (Vinay) locked OUT of all clinic PII routes; org_admin auto-inherits all branches in own org; doctor role added with read-only own-data routes.
- Schema additions enumerated in §3.
- API endpoints enumerated in §5.
- Tests + acceptance criteria in §11.

### OUT of scope (handled by other sub-specs)
- Outbound voice infra (B)
- Pre-appointment 15-min reminder voice calls (C — consumes Doctor.pre_appointment_reminder + Token.appointment_time)
- Post-treatment next-day follow-up voice calls (C — consumes FollowupTask rows of type `post_appt_check`)
- Cascade rebook voice calls (C — consumes FollowupTask rows of type `cascade_rebook` written by this sub-spec)
- Onboarding wizard (D)
- DID provisioning + Vobiz Voice App per clinic (D — depends on Vobiz support reply on Voice App API)
- Owner-side clinic analytics dashboard beyond admin (D)

---

## 3. Schema changes (Alembic migration `2026_06_08_subspec_a.py`)

```sql
-- 3.1 Doctor weekly availability + override + post-treatment-followup default
ALTER TABLE doctors
    ADD COLUMN available_weekdays JSONB NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
    -- JSON array of ints 0-6 (ISO weekday, 0=Monday). Single working_hours_start/end applies to all listed days.
    ADD COLUMN post_treatment_followup BOOLEAN NOT NULL DEFAULT FALSE,
    -- Auto-defaulted at doctor creation: TRUE for booking_type='appointment', FALSE for 'token'.
    ADD COLUMN walkins_closed_today_date DATE,
    -- Receptionist clicks "stop walk-ins" → set to CURRENT_DATE. Auto-clears via date comparison next day.
    ADD COLUMN calendar_event_id_recurring VARCHAR(255),
    -- Token-doctor only: Google Cal event ID of recurring "in clinic hours" event. NULL for slot-doctor.
    ADD COLUMN user_id UUID UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    -- Links Doctor to User (for doctor-role login). Nullable: Doctor row exists before first login.
    ADD COLUMN invited_email VARCHAR(255);
    -- Org_admin types doctor's Google email at Doctor creation. On first sign-in: User.email = invited_email → link.

-- 3.2 Date-specific unavailability override
CREATE TABLE doctor_unavailability (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id            UUID NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
    doctor_id            UUID NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    date                 DATE NOT NULL,
    reason               TEXT,
    created_by_user_id   UUID,  -- plain UUID, no FK (matches Token.marked_by_user_id pattern)
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (doctor_id, date)
);
CREATE INDEX ix_doctor_unavailability_branch_date ON doctor_unavailability(branch_id, date);

-- 3.3 FollowupTask extended for sub-spec C three task types + back-reference to Token
ALTER TABLE followup_tasks
    ADD COLUMN task_type VARCHAR(30) NOT NULL DEFAULT 'post_appt_check',
    -- App-side enum (not DB enum) for growth without DDL:
    --   'post_appt_check'   — next-day "how are you feeling" voice call
    --   'pre_appt_reminder' — 15-min-before reminder voice call
    --   'cascade_rebook'    — doctor cancelled day, call patient to reschedule
    ADD COLUMN token_id UUID REFERENCES tokens(id) ON DELETE RESTRICT;
    -- Links back to original Token for context. Nullable for free-floating follow-ups.

-- 3.4 Token cascade audit + emergency override reason
ALTER TABLE tokens
    ADD COLUMN cancelled_by_user_id UUID,         -- who clicked "doctor unavailable" (audit)
    ADD COLUMN emergency_reason TEXT;             -- required when walk-in bypasses cap via is_urgent=true

-- 3.5 Calendar write queue (Option A retry pattern)
CREATE TABLE calendar_write_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id       UUID NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
    token_id        UUID NOT NULL REFERENCES tokens(id)   ON DELETE RESTRICT,
    operation       VARCHAR(20) NOT NULL,         -- 'create' | 'update' | 'delete'
    payload_json    JSONB NOT NULL,               -- {calendar_id, first_name, last4, dt, duration, doctor_name}
    google_event_id VARCHAR(255),                 -- populated after successful create; reused for update/delete
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending' | 'in_progress' | 'done' | 'failed_permanent'
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_calendar_tasks_status_next ON calendar_write_tasks(status, next_attempt_at);
-- Backoff schedule per attempt: 0s → 5s → 30s → 5min → 60min → failed_permanent (5 attempts total).

-- 3.6 User.role enum gains 'doctor' value
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'doctor';
-- Must run in its own transaction per Postgres rules; Alembic handles via op.execute("COMMIT") + op.execute("ALTER TYPE ...") + op.execute("BEGIN").

-- 3.7 Compound indexes (TD-018 payback)
CREATE INDEX ix_tokens_branch_date         ON tokens(branch_id, date);
CREATE INDEX ix_tokens_branch_doctor_date  ON tokens(branch_id, doctor_id, date);
```

**Migration safety:**
- All ALTER TABLE … ADD COLUMN with DEFAULT use Postgres 11+ instant-default (no table rewrite).
- New tables empty at deploy → no backfill needed.
- ALTER TYPE … ADD VALUE is non-blocking but must run outside a transaction (Alembic recipe handles).
- Existing data preserved: existing Doctor rows get `available_weekdays = [0,1,2,3,4,5,6]` (all days), preserving today's behavior.

---

## 4. CLAUDE.md RULE 4 amendment

**Old (pre-2026-06-08):** "Calendar first, WhatsApp second. Calendar failure = booking failure (raise exception)."

**New (effective 2026-06-08 with sub-spec A merge):**
> DB write FIRST. Calendar write strategy depends on `doctor.booking_type`:
> - `appointment` (slot-based): synchronous Calendar write with inline retry (0s → 2s → 5s; max 7s). Inline fail falls back to async queue + admin alert.
> - `token` (token-based): async Calendar enqueue, drained by worker (0s → 5s → 30s → 5min → 60min → permanent fail).
>
> Booking is committed in DB once Token row written. Voice readback always proceeds.
> PWA Queue page is the canonical doctor view; Google Calendar is a mirror.
> Permanent calendar fail → admin alerted + clinic dashboard banner.
> Token-doctor token bookings do NOT write per-patient Cal events. Token-doctors get recurring "in clinic hours" Cal event for owner availability visibility (calendar_event_id_recurring).

Logged as `TD-RULE4-CHANGE-2026-06-08` in `docs/TECH_DEBT.md` for audit trail. Old rule preserved in TD entry body.

---

## 5. Backend API additions

All endpoints gated by JWT (existing Phase 4 auth) + `assert_branch_access` (extended) + role-specific dependencies.

### 5.1 New routers

| Path | File |
|---|---|
| `/doctors/*` | `backend/routers/doctors.py` (new) |
| `/availability/*` | `backend/routers/availability.py` (new) |
| `/walkin/*` | `backend/routers/walkin.py` (new) |
| `/followup/*` | `backend/routers/followup.py` (new) |
| `/branches/*` | `backend/routers/branches.py` (new) |
| `/doctor/me/*` | `backend/routers/doctor_self.py` (new) |
| `/admin/*` | `backend/routers/admin.py` (extend existing) |

### 5.2 Endpoint catalog

| Endpoint | Method | Purpose | Roles allowed |
|---|---|---|---|
| `/doctors/{branch_id}` | GET | List doctors in branch with weekly + working hours + flags | receptionist, org_admin |
| `/doctors/{branch_id}` | POST | Create doctor (auto-defaults reminder + followup by booking_type) | org_admin |
| `/doctors/{branch_id}/{doctor_id}` | PATCH | Edit working hours, available_weekdays, daily_token_limit, max_concurrent_per_slot, pre_appointment_reminder, post_treatment_followup, invited_email, google_calendar_id | org_admin |
| `/doctors/{branch_id}/{doctor_id}` | DELETE | Soft delete (status=inactive) | org_admin |
| `/doctors/{branch_id}/{doctor_id}/stop-walkins-today` | PATCH | Set walkins_closed_today_date = CURRENT_DATE | receptionist, org_admin |
| `/availability/{branch_id}/{doctor_id}` | POST | Mark unavailable date range → bulk insert + cascade enqueue | org_admin |
| `/availability/{branch_id}/{doctor_id}?from=&to=` | GET | List unavailable dates in range | receptionist, org_admin |
| `/availability/{branch_id}/{doctor_id}/{date}` | DELETE | Remove single date | org_admin |
| `/availability/{branch_id}/{doctor_id}/affected?from=&to=` | GET | Preview tokens that would be cancelled (used by drawer before confirm) | org_admin |
| `/walkin/{branch_id}/preflight?doctor_id=X` | GET | Returns `{allowed, reason, next_slot?}` for adaptive walk-in form | receptionist, org_admin |
| `/walkin/{branch_id}` | POST | Walk-in registration (atomic Token + Calendar enqueue/inline). Body includes optional `is_emergency` + `emergency_reason` | receptionist, org_admin |
| `/followup/{branch_id}/token/{token_id}` | POST | Create FollowupTask after attendance | receptionist, org_admin |
| `/followup/{branch_id}?date=` | GET | List scheduled followups (consumed by sub-spec C worker; visible to receptionist) | receptionist, org_admin |
| `/followup/{branch_id}/{followup_id}` | DELETE | Cancel scheduled followup | receptionist, org_admin |
| `/branches/{branch_id}/calendar` | PATCH | Set/update `branch.google_calendar_id` (validates via empty event probe) | org_admin |
| `/doctor/me/queue?date=today` | GET | Own today's queue + stats | doctor |
| `/doctor/me/schedule` | GET | Own working hours, available_weekdays, upcoming unavailability | doctor |
| `/doctor/me/followups?date=` | GET | Own patients' scheduled followups | doctor |
| `/admin/orgs` | GET | All orgs: id, name, plan, status, owner_email, owner_phone, current_mrr | super_admin only |
| `/admin/orgs/{org_id}/branches` | GET | Branches metadata (excludes google_calendar_id) | super_admin only |
| `/admin/orgs/{org_id}/usage?from=&to=` | GET | Aggregate inbound/outbound minutes + bookings + calls (COUNT/SUM only) | super_admin only |
| `/admin/orgs/{org_id}/billing` | GET | BillingCycle history | super_admin only |
| `/admin/orgs/{org_id}/contacts` | GET | Owner phone/email + branch emergency contacts | super_admin only |
| `/admin/warnings` | GET | Active warnings (overage approaching, trial expiring, Cal broken, failed payment, churn signal) | super_admin only |
| `/admin/pnl?from=&to=` | GET | Revenue − costs = profit | super_admin only |
| `/admin/lifetime-totals` | GET | patients_booked, calls_handled, minutes_used, branches_live | super_admin only |

### 5.3 Walk-in over-cap response contract
```json
HTTP 422
{
  "error": {
    "code": "OVER_CAPACITY",
    "message": "Daily token limit reached (10/10)",
    "details": { "current": 10, "limit": 10, "override_path": "emergency" }
  }
}
```
Frontend offers emergency override checkbox → resubmits with `is_emergency=true` + `emergency_reason` body field.

### 5.4 RBAC: assert_branch_access (extended)
```python
def assert_branch_access(user, branch_id, db):
    if user.role == 'super_admin':
        raise HTTPException(403, "Platform admin cannot access clinic PII; use /admin endpoints")
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(404)
    if user.role == 'org_admin':
        if branch.org_id != user.org_id:
            raise HTTPException(403)
        return  # org_admin auto-inherits all branches in own org
    # receptionist + doctor
    if str(branch_id) not in (user.branch_ids or []):
        raise HTTPException(403)
```

### 5.5 require_admin (existing) — unchanged
Used by all `/admin/*` routes. Returns 403 if `user.role != 'super_admin'`.

### 5.6 forbid_admin (new) — defense in depth
```python
def forbid_admin(user = Depends(get_current_user)):
    if user.role == 'super_admin':
        raise HTTPException(403, "Use /admin endpoints")
    return user
```
Applied to PII-touching routes that don't use assert_branch_access (e.g. `/doctor/me/*`).

### 5.7 New background jobs

| Job | Cadence | Purpose |
|---|---|---|
| `backend/jobs/calendar_writer.py` | every 30 s | Drain `calendar_write_tasks WHERE status='pending' AND next_attempt_at <= NOW()` |
| `backend/jobs/admin_warning_scanner.py` | every 1 h | Compute overage/trial/Cal-broken/churn signals → write to admin_warnings cache (or compute on-demand in `/admin/warnings` if cheap) |

Wired into `backend/main.py` lifespan AsyncIOScheduler.

### 5.8 Audit
Every PATCH/POST/DELETE wrapped with `@audit("doctor.update", resource_type="doctor")`, etc. Existing PII denylist enforces no patient/doctor names in `metadata_json`.

Key audit events introduced:
- `walkin.created`, `walkin.emergency_override`
- `doctor.create`, `doctor.update`, `doctor.delete`
- `availability.mark_unavailable`, `availability.remove`
- `availability.cascade_cancel` (1 row per cancelled token)
- `followup.created`, `followup.deleted`
- `calendar.write.success`, `calendar.write.failed_permanent`
- `admin.orgs.list`, `admin.usage.read`, `admin.pnl.read`, etc.
- `user.link_google_sub` (first sign-in linking)
- `access_denied` (403 path)
- `doctor.walkins_closed_today`

### 5.9 Rate limiting (extend Phase 4.5 fastapi-limiter)
- `POST /walkin` — 30 req/min per user
- `POST /availability` — 10 req/min per user
- `POST /followup` — 30 req/min per user
- `GET /admin/*` — 60 req/min per user

---

## 6. Google Calendar service architecture

### 6.1 File structure
```
backend/services/calendar_service.py    ← REAL impl, importable from agent/
agent/services/calendar_stub.py         ← DELETED
agent/services/calendar_proxy.py        ← NEW thin shim: re-exports backend service for agent runtime
```

`agent/` imports `from backend.services.calendar_service import GoogleCalendarService` (both runtimes share the file). Both Render + Fly mount the SA JSON via env var.

### 6.2 Auth (Option A — service account)
- Single Google Cloud project owned by Vinay → 1 service account → JSON downloaded
- Production: `GOOGLE_SA_JSON_B64` env var (base64-encoded JSON), decoded at app boot → `/tmp/google-sa.json`
- Dev: `GOOGLE_APPLICATION_CREDENTIALS=./google-service-account.json` (file in repo root, **gitignored**)
- Scope: `https://www.googleapis.com/auth/calendar.events` (least privilege)

### 6.3 Onboarding step per clinic
Documented in sub-spec D wizard:
1. Owner opens Google Calendar → Settings & Sharing → Share with specific people
2. Adds `vachanam-events@<project>.iam.gserviceaccount.com`
3. Permission: "Make changes to events"
4. Owner copies Calendar ID (Settings → Integrate calendar → Calendar ID, format `xxx@group.calendar.google.com`)
5. Pastes into onboarding wizard → saved to `branch.google_calendar_id`

Wizard validates via empty event probe (create test event → delete immediately) before saving.

### 6.4 Service interface (concrete)
```python
class GoogleCalendarService:
    def __init__(self, sa_json_path: str | None = None): ...

    # SLOT-DOCTOR PATH (per-patient blocking event)
    # NOTE: Called ONLY for doctor.booking_type='appointment'. Token-doctor bookings
    # never invoke this method (see 6.5 for token-doctor calendar policy).
    async def create_booking_event(
        self,
        calendar_id: str,
        patient_first_name: str,
        patient_phone_last4: str,        # "5891" — never full phone
        appointment_dt: datetime,        # IST tz-aware
        duration_minutes: int,
        doctor_name: str,
    ) -> str:                            # returns google event_id
        # Summary: "Apt — Suresh (xx5891)"
        # Description: "" (PII rule — no medical, no full phone)
        # End: start + duration_minutes
        # Wraps sync google API in asyncio.to_thread
        ...

    # TOKEN-DOCTOR PATH (recurring availability event)
    async def upsert_doctor_hours_event(
        self,
        calendar_id: str,
        doctor_name: str,
        working_hours_start: time,
        working_hours_end: time,
        available_weekdays: list[int],   # ISO 0=Mon
        existing_event_id: str | None,
    ) -> str:                            # returns event_id
        # Summary: "Dr Sharma — clinic hours"
        # Time: working_hours_start to working_hours_end IST
        # RRULE: FREQ=WEEKLY;BYDAY=MO,WE,FR (mapped from available_weekdays)
        # On existing_event_id → events().update(); else events().insert()
        ...

    async def delete_event(self, calendar_id: str, event_id: str) -> None: ...
    async def update_event(self, calendar_id: str, event_id: str, new_dt: datetime) -> None: ...
```

### 6.5 Token-doctor calendar policy
- Token-doctor token bookings do NOT write per-patient Cal events (per Vinay 2026-06-08).
- Token-doctor uses `upsert_doctor_hours_event` to write a single recurring "in clinic hours" event to `branch.google_calendar_id`. Event ID stored on `doctor.calendar_event_id_recurring`.
- Called as side-effect of POST/PATCH /doctors when `working_hours_start`, `working_hours_end`, or `available_weekdays` change.
- Slot-doctor does NOT use this method; their bookings produce per-event entries instead.

### 6.6 Calendar-id resolution (slot-doctor)
Precedence:
1. `doctor.google_calendar_id` (doctor's own calendar if set)
2. `branch.google_calendar_id` (clinic-wide shared)
3. Raise `CalendarNotConfiguredError` → booking proceeds (DB write succeeds) + `calendar_write_tasks` row marked `failed_permanent` immediately → admin alert

### 6.7 Hybrid sync/async write logic
```python
async def confirm_booking(token, doctor, calendar_id_or_none, ...):
    # Step 1: DB write — always
    db.add(token); await db.commit()

    # Step 2: calendar path varies
    if doctor.booking_type == 'token':
        return token  # no per-patient Cal event for token-doctor

    if calendar_id_or_none is None:
        await enqueue_calendar_task(token, operation='create', payload=payload, status='failed_permanent')
        await alert_admin('calendar_not_configured', branch_id, token_id)
        return token

    if doctor.booking_type == 'appointment':
        # SYNC path — low volume, doctor relies on Cal slot times
        try:
            event_id = await _cal_write_with_inline_retry(payload, max_attempts=3, backoff=[0, 2, 5])
            token.google_calendar_event_id = event_id
            await db.commit()
        except CalendarWriteFailed:
            await enqueue_calendar_task(token, operation='create', payload=payload)
            await alert_admin('calendar_sync_fail', branch_id, token_id)
    return token
```

### 6.8 Worker (drains async queue)
```python
async def run_calendar_writer():
    """APScheduler job, every 30s."""
    pending = await db.execute(select(CalendarWriteTask).where(
        CalendarWriteTask.status == 'pending',
        CalendarWriteTask.next_attempt_at <= datetime.utcnow(),
    ).limit(50))
    for task in pending:
        task.status = 'in_progress'; await db.commit()
        try:
            event_id = await _do_calendar_op(task)
            task.status = 'done'; task.google_event_id = event_id
            if task.operation == 'create':
                token = await db.get(Token, task.token_id)
                token.google_calendar_event_id = event_id
            await db.commit()
        except Exception as e:
            task.attempts += 1
            task.last_error = str(e)[:500]
            if task.attempts >= 5:
                task.status = 'failed_permanent'
                await alert_admin('calendar_write_failed_permanent', task.branch_id, task.token_id)
            else:
                # backoff: 5s, 30s, 5min, 60min after attempts 1, 2, 3, 4
                delay = [5, 30, 300, 3600][task.attempts - 1]
                task.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
                task.status = 'pending'
            await db.commit()
```

---

## 7. PWA architecture

### 7.1 Stack (final)
```
React 18                    # locked from Phase 7
Vite 5                      # locked
TailwindCSS 3               # locked
React Router v6             # routes
TanStack Query v5           # server state, optimistic mutations
Workbox via vite-plugin-pwa # service worker, BackgroundSync
axios + JWT interceptor     # auth
Framer Motion 11            # animations (card reorder, count-up)
Sonner                      # toast notifications (Emilkowalski)
Vaul                        # mobile bottom-sheet drawers (Emilkowalski)
@hookform/resolvers + zod   # form validation
date-fns + date-fns-tz      # IST date math
idb-keyval                  # IndexedDB wrapper for offline queue
recharts                    # admin dashboard charts (Layout A)
```

Initial JS budget: <200 KB gzipped. Lazy-load Doctor/Admin/Followup routes.

### 7.2 Route map
```
/                       → role-based redirect
/login                  → Google Sign-In (existing Phase 4 auth)
/queue                  → today's queue (default for receptionist)
/walkin                 → walk-in registration page (also openable from /queue as drawer)
/doctors                → doctor list
/doctors/:id            → doctor detail/edit
/doctors/:id/leave      → mark unavailability drawer route (deep-linkable)
/followups              → today's scheduled followups
/me                     → doctor self-view (read-only own queue + schedule)
/admin                  → Vinay's mission control (Layout A)
/admin/orgs/:id         → per-clinic drill: branches, billing, contacts
```

### 7.3 State layers

**Server state (TanStack Query keys):**
- `['queue', branchId, todayISO]` — 30 s poll + on focus
- `['doctors', branchId]` — on focus
- `['doctor', branchId, doctorId]` — on focus
- `['unavailability', branchId, doctorId, yearMonth]` — on focus
- `['followups', branchId, dateISO]` — on focus
- `['preflight', branchId, doctorId]` — staleTime 5 s
- `['admin', 'mtd']` — 60 s poll
- `['admin', 'warnings']` — 60 s poll

**Client state (React Context):**
- `auth` → `{ jwt, user, branchIds, isAdmin }`
- `activeBranch` → uuid
- `offlineFlag` → bool

**Persisted (IndexedDB via idb-keyval):**
- `jwt` → string
- `lastQueueSnapshot` → QueueResponse (cold-start offline render)
- `mutationQueue` → `QueuedMutation[]`

### 7.4 Offline behavior
Per Section 6 (Offline + error handling) drafted in brainstorm. Key rules:
- All POST/PATCH/DELETE route through `mutationProxy(req)` → enqueue on fail, optimistic UI kept.
- Walk-in registration BLOCKED offline (needs Redis INCR for atomic token assignment).
- Emergency walk-in override BLOCKED offline (audit + reason validation).
- Cascade cancellation BLOCKED offline (server confirmation of affected tokens required).
- Mark attended/no-show, schedule followup, doctor edit, unavailability listing — all queue cleanly.

Workbox cache strategies per route documented in §10.

### 7.5 Auth + RBAC client-side
- JWT stored in IndexedDB
- axios interceptor adds `Authorization: Bearer`
- 401 → wipe JWT + redirect /login
- Nav items render based on `user.role`:
  - receptionist: Queue, Walk-in, Doctors (read), Followups
  - org_admin: Queue, Walk-in, Doctors, Followups, Dashboard, Branch switcher
  - doctor: Me, Schedule
  - super_admin: Admin only (no clinic-side nav items)

Branch switcher visible when `user.branch_ids.length > 1`.

### 7.6 Animation polish
- Queue card: Framer Motion `layout` prop → automatic reorder on attendance
- Admin KPI cards: stagger-fade-in on load (50 ms apart)
- Admin numbers: `useCountUp` hook
- Warning chip: subtle pulse on red severity
- Drawer (Vaul): native momentum scroll, swipe-to-close
- Toast (Sonner): bottom-stack, 4 s auto-dismiss, success/error/info variants

### 7.7 Error boundaries (3 layers)
1. **React root** → "Something broke. Reload?" + auto-reload after 5 s + log stack to `/client-errors`
2. **Route-level Suspense + ErrorBoundary** → page-level fallback
3. **TanStack Query error** → inline retry on card + Sonner toast

### 7.8 Per-page UX (from Section 5 mockups)
- **Queue page** — Hero number ("12 remaining today"), per-doctor sections with voice/walk-in/emergency card variants (orange/red left borders), unavailable doctor section dimmed with CLOSED badge, attended-section collapse, 52 px tap targets.
- **Walk-in** — adaptive form: token-doctor shows token-only confirm; slot-doctor shows slot picker with N/max occupancy; over-cap → reject + emergency override checkbox with reason field.
- **Doctor edit** — name, specialization, booking_type toggle, weekday picker (7 chips), working hours single range, daily_token_limit, max_concurrent_per_slot (slot-doctor only), pre/post-treatment toggles, Google Cal field with "test connection", invited Google email field.
- **Doctor unavailability drawer** — from/to date pickers, reason field, pre-fetched affected tokens list, "Confirm + notify N patients" cascade button.
- **Followup drawer** — when (default tomorrow 9 AM), what-to-ask textarea, max attempts dropdown, consent gate. Hidden for token-doctor patients unless `Doctor.post_treatment_followup=true`.
- **Admin dashboard (Layout A — Mission Control)** — 2-row KPI strip (MTD + Lifetime), warnings (3 severities), usage trend chart, revenue-by-plan, clinics table with row drill, cost breakdown.

### 7.9 Vinay-specific polish (admin page)
- Real number layout (typographic), monospace for currency
- Subtle background gradient on KPI cards
- Tooltip on each metric explaining the source query
- Click any clinic row → slide-right detail panel (no full route nav for fast review)
- Keyboard shortcuts: `c` for clinics, `w` for warnings, `?` for help

---

## 8. Walk-in timing rules (per booking_type)

Per Vinay 2026-06-08:
- **Slot-based:** walk-in allowed at ANY time during working hours. Picks next-available slot from current time forward.
- **Token-based:** walk-in allowed until ANY of:
  - `walkins_closed_today_date == today` (receptionist explicitly stopped)
  - `current_time >= doctor.working_hours_end` (clinic hours over)
  - daily_token_limit reached (existing hard cap)
  - doctor unavailable today (DoctorUnavailability or weekday not in available_weekdays)

Emergency override bypasses all four blocks; sets `Token.is_urgent=true` + `Token.emergency_reason` required.

Preflight endpoint `/walkin/{branch}/preflight?doctor_id=X` returns:
```json
{
  "allowed": false,
  "reason": "DAILY_LIMIT_REACHED",
  "details": { "current": 10, "limit": 10 },
  "override_path": "emergency"
}
```
or
```json
{
  "allowed": true,
  "next_slot": "15:30"   // appointment-doctor only
}
```

---

## 9. Cascade cancellation flow

When `org_admin` marks doctor unavailable for a date range (single API call, multi-day):

1. Single DB transaction:
   - `INSERT INTO doctor_unavailability` (one row per date, `ON CONFLICT DO NOTHING`)
   - `SELECT tokens FOR UPDATE WHERE doctor_id=X AND date BETWEEN from AND to AND status='confirmed'`
   - `UPDATE tokens SET status='cancelled_by_clinic', cancelled_by_user_id=:user_id` for each
   - `INSERT INTO followup_tasks` with `task_type='cascade_rebook'`, `token_id=...`, `what_to_ask='Doctor unavailable on <date>. Reschedule.'`, `scheduled_at=now+1min`
2. Outside the transaction (best-effort):
   - `INSERT INTO calendar_write_tasks` (operation=delete) for each cancelled Token with non-null `google_calendar_event_id` (only slot-doctor cancellations)
3. Audit row per cancelled Token: `availability.cascade_cancel`
4. Response: `{ unavailable_dates: 14, cancelled_tokens: 8, followups_scheduled: 8 }`

Sub-spec C's outbound voice worker drains the `cascade_rebook` FollowupTasks within 1 minute and dials each patient to offer reschedule.

---

## 10. Workbox cache strategies

| URL pattern | Strategy | Max age | Reason |
|---|---|---|---|
| `/queue/{branch}/today` | NetworkFirst, 3 s timeout → cache | 30 s | Fresh-when-online, cached when offline |
| `/doctors/*` | StaleWhileRevalidate | 5 min | Rarely changes; render fast |
| `/availability/*` | StaleWhileRevalidate | 5 min | Same |
| `/admin/*` | NetworkOnly | — | Admin always fresh; no offline mode |
| `/walkin/*` | NetworkOnly | — | Cannot queue (Redis INCR required) |
| `/followup/*` POST | BackgroundSync | — | Replays on reconnect |
| `/auth/*` | NetworkOnly | — | Never cache auth |
| Static (JS, CSS, fonts, icons) | CacheFirst | 30 d | Versioned by Vite hash |

---

## 11. Tests + acceptance criteria

### 11.1 Test files to create

**Unit (tests/unit/):**
- `test_calendar_service_real.py` — mock googleapiclient; PII format compliance; RAISES on cred error
- `test_calendar_service_doctor_hours.py` — RRULE generation from available_weekdays (Mon/Wed/Fri → `BYDAY=MO,WE,FR`)
- `test_slot_capacity.py` — `check_slot_available` with N/max combos
- `test_walkin_preflight.py` — all 4 block reasons + emergency override path
- `test_walkin_emergency_override.py` — over-cap rejection then bypass + audit row + `is_urgent=true`
- `test_cascade_enqueue.py` — mark unavailable → bulk unavailability + cancelled tokens + followups + cal_write_tasks (single tx)
- `test_calendar_writer_backoff.py` — retry schedule + permanent fail transition
- `test_assert_branch_access_super_admin_blocked.py` — super_admin → 403 on `/queue/{branch_id}/today`
- `test_doctor_create_defaults.py` — booking_type='appointment' → pre+post followup True; 'token' → both False
- `test_org_admin_branch_inheritance.py` — org_admin without branch_ids → access all branches in own org

**Integration (tests/integration/):**
- `test_walkin_e2e.py` — POST /walkin → Token + Redis INCR + cal_write_tasks row
- `test_cascade_e2e.py` — POST /availability range with 5 pre-existing tokens → 5 cancelled + 5 followups + 5 cal_write_tasks
- `test_calendar_writer_e2e.py` — real worker → real Cal API → marks done + event_id on token
- `test_admin_pii_isolation.py` — super_admin can GET /admin/orgs but 403 on /queue, /doctors, /walkin, /followup
- `test_doctor_self_routes.py` — doctor role can GET /doctor/me/queue but not /queue/{branch}/today
- `test_doctor_hours_recurring_event.py` — PATCH doctor weekly → upsert recurring event in Cal

**Edge cases (tests/edge_cases/):**
- `test_walkin_concurrent_tokens.py` — N=10 concurrent walk-ins, daily_limit=10 → exactly 10 succeed
- `test_calendar_outage_async_path.py` — token-doctor (no per-patient Cal) → no failures, no enqueue
- `test_calendar_outage_sync_path.py` — appointment-doctor + Cal API fails 3× inline → falls back to async queue → booking still confirms
- `test_offline_walkin_blocked.py` — SW sim offline → walkin POST queued, user sees "needs internet" toast
- `test_branch_isolation_cascade.py` — receptionist of branch A marks unavailable → only branch A tokens cancelled

**Frontend (tests/frontend/, Vitest + Playwright):**
- Component snapshots: PatientCard, WalkInDrawer, FollowupDrawer, AdminKpiStrip
- Hook test: useQueue offline mutation queue replay
- E2E: receptionist login → mark attended → schedule followup → go offline → mark another attended → reconnect → see synced

### 11.2 Acceptance gate (all must pass)
```
[ ] Google Calendar real impl: creates events in test calendar, PII format verified
[ ] Calendar write queue: backoff schedule honored, permanent fail → admin alert
[ ] Token-doctor working hours sync to Cal as recurring event (RRULE correct)
[ ] Slot-doctor booking writes per-patient Cal event blocking [start, start+duration]
[ ] Booking succeeds 100% in DB even when Cal fails (DB-first guarantee)
[ ] DoctorUnavailability table + cascade flow: mark range → tokens cancelled + followups enqueued
[ ] Receptionist PWA opens at localhost:5173 with Google login
[ ] Queue page renders today's queue, attend/no-show works optimistic + offline-queued
[ ] Walk-in token-doctor: assigns next token via Redis INCR
[ ] Walk-in slot-doctor: picks free slot with N/max display
[ ] Walk-in over-cap: hard cap rejection unless emergency override
[ ] Walk-in emergency override: requires reason text, audited, is_urgent=true
[ ] Walk-in timing: token-doctor blocked after working_hours_end + after daily_limit + after walkins_closed_today_date
[ ] Walk-in timing: slot-doctor blocked when no future slot has capacity today
[ ] "Stop walk-ins" flag persists per-day, auto-clears next day
[ ] Doctor edit: working hours + weekday toggle + daily_limit + max_concurrent + reminders + followup toggle + invited_email
[ ] Doctor edit: mark unavailable bottom-sheet shows affected tokens before confirm
[ ] Followup drawer: appears for appointment-doctor patients, scheduled date + message saved
[ ] Followup drawer: hidden for token-doctor patients unless Doctor.post_treatment_followup=true
[ ] Followup consent gate: Patient.followup_consent=false → schedule button disabled
[ ] Admin dashboard Layout A: 2-row KPI strip + warnings + clinic table + cost breakdown + lifetime totals
[ ] Admin RBAC: super_admin 403s on all clinic-PII routes (/queue, /doctors, /walkin, /followup, /availability)
[ ] Org admin auto-accesses all org's branches without branch_ids manipulation
[ ] Receptionist scoped to branch_ids: other branch → 403
[ ] Doctor read-only own-data routes
[ ] First-time User link populates google_sub + clears invited_email + audit row
[ ] PWA installs to home screen (manifest + icons), opens without browser chrome
[ ] PWA service worker caches last queue snapshot, opens offline with cached data
[ ] Mutation queue replays on online event with Sonner success toast
[ ] All 207+ existing tests still pass (no regressions)
[ ] New tests: 30+ unit, 10+ integration, 6+ edge case, 5+ frontend = 51+ new tests
[ ] CI green
[ ] Zero secrets in repo (Phase 4.5 secrets-scan still green)
[ ] DPDP: aggregate-only queries in /admin/* (no SELECT * patterns)
[ ] CLAUDE.md RULE 4 amended and committed
[ ] TD-RULE4-CHANGE-2026-06-08 logged
[ ] TD-018 closed (compound indexes shipped)
[ ] TD-025 closed (narrow except in queue.py)
[ ] No regression to TD-027 retention scope
```

---

## 12. Open questions / decisions deferred

None at spec close. All decisions resolved during brainstorm:
- Calendar auth = Option A (service account) ✓
- Doctor weekly = same hours all available days ✓
- Cascade = auto-cancel + enqueue voice followup ✓
- Walk-in = hard cap, emergency override only ✓
- Phone optional on walk-in ✓
- Availability owner = org_admin/receptionist (not doctor self-service) ✓
- Calendar fail = DB-first hybrid (sync for slot, async for token) ✓
- Token-doctor = no per-patient Cal events ✓
- Slot-doctor = per-patient Cal events ✓
- Walk-in timing rules per booking_type ✓
- Defaults: pre-reminder + post-followup = booking_type='appointment' ✓
- RBAC: 4 roles (super_admin, org_admin, receptionist, doctor) ✓
- super_admin locked OUT of clinic PII ✓
- Admin dashboard = Layout A Mission Control ✓
- Lifetime totals included in KPI strip ✓
- PWA stack: Phase 7 base + Framer Motion + Sonner + Vaul ✓

---

## 13. Sub-spec dependencies

```
A (this spec) — Calendar + PWA + RBAC
    │
    ├─→ B (Outbound voice infra) — Vobiz make_call wrapper + Pipecat outbound session helpers
    │    │
    │    └─→ C (Follow-up flows) — pre-appt reminder + post-treatment call + cascade rebook
    │         (consumes FollowupTask rows + Doctor.pre_appointment_reminder + Doctor.post_treatment_followup written by A)
    │
    └─→ D (Onboarding + DID + dashboards UI) — Vobiz Voice App per clinic + owner-side dashboards
         (extends Admin dashboard from A with per-clinic drill UI)
```

---

## 14. Effort estimate

| Track | Effort |
|---|---|
| Schema migration + Alembic | 0.5 d |
| Calendar service real impl + worker | 1 d |
| Backend routers (doctors, availability, walkin, followup, branches, doctor_self) | 1.5 d |
| Admin router extensions + watchlist scanner | 1 d |
| RBAC tightening + tests | 0.5 d |
| PWA bootstrap (stack, build, auth, error boundaries) | 1 d |
| Queue page | 0.5 d |
| Walk-in page + drawer + adaptive form | 1 d |
| Doctors page + edit + unavailability drawer | 1 d |
| Followup drawer | 0.5 d |
| Admin dashboard Layout A + drill panels | 1.5 d |
| Doctor self view | 0.3 d |
| Tests (unit + integration + edge + frontend) | 1.5 d |
| Polish + Framer/Sonner/Vaul wiring | 0.5 d |
| **Total** | **~12 working days** (solo, no blockers) |

---

## 15. Pre-flight checklist before plan starts

- [ ] Vinay manually shares a test personal-Gmail Calendar with the SA email + confirms `events.insert` returns 200 (5-min sanity test from verification GAP)
- [ ] `GOOGLE_SA_JSON_B64` env var added to Render
- [ ] `.gitignore` already excludes `.env` and `google-service-account.json` (verify)
- [ ] `.gitignore` includes `.superpowers/` (add if missing)
- [ ] Sub-spec A scope locked (this doc) before plan generation

---

End of spec.
