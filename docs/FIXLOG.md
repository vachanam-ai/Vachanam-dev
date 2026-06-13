# FIXLOG — every fix, its proof, and its regression status

Process (Vinay, 2026-06-12): every fix lands here with a regression guard.
After EVERY new fix: (1) run the full suite — all guards below must stay
green; (2) re-check any ⚠ manual items touched by the change. Step-by-step
upgrades, nothing previously fixed may silently break.

Legend: ✅ automated regression test · ⚠ manual check (no automated guard yet)

| # | Date | Issue (symptom) | Root cause | Fix commit | Regression guard |
|---|------|-----------------|------------|-----------|------------------|
| 1 | 06-11 | Inbound ringing, never answered | Hard `wait_for_participant()` before `session.start()` + missing asyncio import | d569103 | ⚠ manual call test |
| 2 | 06-11 | Telugu horrible + tools failing all call | `attempt_timeout=3s` < Google min 10s deadline → every turn fell to GPT-4o-mini, which hallucinated doctor UUIDs | 8dceff7 | ⚠ config — comment in `_build_fallback_llm` |
| 3 | 06-11 | Booking failed after 2 retries | Wrong calendar class injected (new kwargs vs legacy signature) → TypeError | 6a86912 | ✅ test_bug_fixes (calendar path exercised) |
| 4 | 06-11 | Routing always default doctor | Gemini wraps JSON in ``` fences → parse fail | 6a86912 | ⚠ fence-strip in route_to_doctor |
| 5 | 06-11 | 5-8s replies | Gemini 2.5 Flash thinking ON by default | 6a86912 | ⚠ thinking_budget=0 both LLM paths |
| 6 | 06-11 | Garbage reg data accepted | No validation | 069a1b2 | ✅ test_validators + test_register_otp |
| 7 | 06-11 | Clinic B could claim Clinic A's DID | No uniqueness on did_number | e008e62 | ✅ test_did_hijack |
| 8 | 06-11 | Agent thought today = June 19, refused valid dates | LLM has no clock; guessed wrong year | 18518de | ⚠ TODAY line injected per call |
| 9 | 06-11 | Family booking attached to wrong patient | Patient matched by phone only | 18518de | ✅ test_register_otp + dup-guard tests |
| 10 | 06-11 | Call #2 onward rang forever | Module-level SQLAlchemy engine bound to call #1's dead event loop | 0c0b30c | ✅ whole suite runs on loop-aware engine |
| 11 | 06-11 | "already booked" echo after success | Second confirm_booking hit dup guard | 0c0b30c | ⚠ prompt step 7 |
| 12 | 06-11 | New doctors missing from calendar | Hours sync was token-doctors-only | 0c0b30c | ⚠ doctors router `_maybe_upsert` |
| 13 | 06-12 | Spoken phone garbled → split patients | No phone validation on voice path | bbcfb6b | ✅ invalid_phone path in confirm_booking |
| 14 | 06-12 | Confirmed slot looked free (dbl-book risk) | Redis restart wiped slot keys; Redis was sole truth | bbcfb6b | ✅ DB-count check in assign/availability |
| 15 | 06-12 | Free 4pm slot reported "not free" | LLM passed zero-width window (4pm-4pm) | bbcfb6b | ⚠ window expansion in check_availability |
| 16 | 06-12 | Doctor on leave: nobody called patients | No job dispatched cascade_rebook tasks | bbcfb6b | ⚠ scheduler job registered (main.py) |
| 17 | 06-12 | Hung up on patient's question (rebook) | LLM judged question as decline | 08eb6ea | ⚠ end_call STRICT docstring + prompt |
| 18 | 06-12 | ISO date read digit-by-digit | Raw date into TTS template | 65f2679 | ✅ telugu_dates assertions |
| 19 | 06-12 | "Rescheduled" but nothing in calendar, old cancelled | LLM treated assign_token hold as booked, skipped confirm | 0d79fe1 | ✅ cancel hard-guard + test_bug_fixes |
| 20 | 06-12 | Rebook call restarted new-patient flow on mumble | Generic booking flow overrode outbound context | 6e9ba5b | ⚠ identity-known override in both EXTRAs |
| 21 | 06-12 | /availability reload → {"detail":"Not Found"} | Vite proxied page-route prefixes to FastAPI | e3cea9c | ⚠ html-bypass in vite.config |
| 22 | 06-12 | One booking became two on June 14 | Reschedule orchestration split across LLM steps | 4b5e7bb | ✅ test_reschedule_atomic_one_confirmed_booking |
| 23 | 06-12 | (latent) transient calendar error → duplicate rows | Function-level @retry re-ran with pending Token in session | 4b5e7bb | ✅ test_confirm_booking_transient_calendar_failure_single_row |
| 24 | 06-12 | (latent) cancelled token number reissued to next patient | Cancel DECR'd the token counter (= number sequence) | 4b5e7bb | ✅ test_cancelled_token_number_never_reissued |
| 25 | 06-12 | Same-day reschedule blocked as "already booked" | Dup guard saw the booking being replaced | 4b5e7bb | ✅ test_reschedule_atomic (would fail without exclude) |
| 26 | 06-12 | Rebook call: "you don't have any booking" | find_my_bookings only returns confirmed; cascade had cancelled it | 06-12 charts commit | ✅ test_find_bookings_includes_recent_cancelled |
| 27 | 06-12 | Rebook call: "unable to find details of Dr Test Kumar" | LLM passed unmatched doctor name; state had no doctor pre-selected on outbound | 06-12 charts commit | ⚠ doctor_id now in dispatch metadata → state pre-select (both jobs) |
| 28 | 06-12 | Leave invisible on owner dashboard | Card existed but per-date rows; now grouped "from X to Y" ranges; API verified returning rows (manual JWT test) | 06-12 charts commit | ⚠ hard-refresh / re-login needed for stale sessions |
| 29 | 06-12 | Booking confirmed without the year | No year rule in prompt; "year only when it matters" left it out of read-backs | 06-12 test-round-3 | ⚠ prompt DATES rule + step 6 (year mandatory in confirmations) |
| 30 | 06-12 | Asked time full → no nearby suggestion | Availability listed ALL free windows, not the ones nearest the asked time | 06-12 test-round-3 | ✅ test_check_availability_offers_nearest_time |
| 31 | 06-12 | Arm pain routed to dentist | Router LLM forced to match; unmatched fell to DEFAULT doctor — no out-of-scope path existed | 06-12 test-round-3 | ✅ test_route_out_of_scope_lists_specialties + vague-still-defaults |
| 32 | 06-12 | Random ధన్యవాదాలు, call ended | STALE prompt block claimed "system ends call after 3 repeats" (no such handler in LiveKit agent — LLM emulated it); no code guard on end_call | 06-12 test-round-3 | ✅ test_end_call_blocked_while_booking_unconfirmed + prompt block replaced |
| 33 | 06-12 | Patient details sometimes not asked | Prompt-only rule, nothing enforced | 06-12 test-round-3 | ✅ test_confirm_booking_first_time_patient_requires_age (+ known-patient skip) |
| 34 | 06-12 | Rebook call: asked cancel → "no booking existed" | Booking already cancelled_by_clinic; cancel returned bare not_cancellable_*; no decline tool — retry loop kept calling every 30min | 06-12 test-round-3 | ✅ test_decline_rebook_completes_followup_task + already_cancelled instruction |
| 35 | 06-12 | Correct name+number → "not matching" | find_my_bookings exact-matched phone strings; SIP caller-ID formats (+91/0/bare) ≠ stored E.164 → empty result → agent asked number → STT garbled it | 06-12 test-round-3 | ✅ test_find_bookings_matches_any_phone_format (4 formats) |
| 36 | 06-12 | "Book at 3" booked 3 AM (outside doctor hours) | confirm_booking trusted the LLM's appointment_time blindly (no working-hours check, token-doctor strays stored); assign_token skipped ALL validation when slot grid empty; no hard hours bound anywhere; no prompt rule for bare spoken numbers | 06-12 3am-fix | ✅ 4 tests: assign+confirm refuse outside hours, token stray time dropped, unconfigured schedule refused; prompt TIME INTERPRETATION rule |
| 37 | 06-12 | (bounty B1) Cancelled appointments stayed on Google Calendar forever | cascade_cancel enqueued delete tasks with calendar_id=None; writer used it verbatim → 5 fails → failed_permanent | 06-12 bounty-r1 | ✅ test_cascade_delete_resolves_calendar_id |
| 38 | 06-12 | (bounty B2) Outbound calls would hit wrong tenant with 2+ clinics | No branch_id in dispatch metadata; agent fell back to global DID for outbound | 06-12 bounty-r1 | ⚠ branch_id in both jobs' metadata + agent prefers it for outbound |
| 39 | 06-12 | (bounty B3) Queue/analytics/walk-in/stop-walkins "today" = server UTC | date.today() on UTC server ≠ branch-local date 00:00–05:30 IST → bookings invisible in that window | 06-12 bounty-r1 | ⚠ _branch_today helper used in queue, walk-in, analytics, stop-walkins |
| 40 | 06-12 | (bounty B4) Queue showed booking-creation timestamp as appointment time | PatientEntry lacked appointment_time; UI sliced confirmed_at (UTC) | 06-12 bounty-r1 | ⚠ appointment_time in payload + Queue.jsx renders it |
| 41 | 06-12 | (bounty B5) Late-night reminders silently never fired | time-only window wrapped past midnight (lo>hi matched nothing) | 06-12 bounty-r1 | ✅ test_reminder_window_midnight_wrap + afternoon case |
| 42 | 06-12 | (bounty B6) Ambiguous doctor name silently booked first match | _resolve_doctor_id substring matched, returned first of several | 06-12 bounty-r1 | ✅ test_resolve_doctor_id_ambiguous_name_refuses |
| 43 | 06-12 | (bounty B7, latent) LLM-echoed token_number persisted | confirm_booking stored the model's copy, discarding the Redis-reserved value | 06-12 bounty-r1 | ⚠ agent wrapper overrides with state.token_number when held |
| 44 | 06-12 | (bounty B8) Phoneless reminder tokens rescanned every minute forever | no-phone branch set reminder_sent but never committed | 06-12 bounty-r1 | ⚠ commit moved before phone check |
| 45 | 06-12 | (bounty B9+B11) 50 calendar clients/tick; analytics raw-string UUID | per-task GoogleCalendarService(); no 400 guard on branch_id | 06-12 bounty-r1 | ⚠ one svc per tick; UUID validated before access check |
| 46 | 06-12 | 20 fake "Replay Clinic" orgs + false ₹7,999 revenue on admin console | test_otp_code_is_single_use lacked the db fixture → its successful /register wrote to the PRODUCTION Neon DB on every suite run; my Console-Clinic fixture rode the same hole earlier | 06-12 fresh-start | ✅ db param added with explanatory docstring; AST sweep confirmed it was the only app-WRITING test without db; DB wiped via scripts/wipe_clinics.py (orgs 20→0, users 24→3 super_admins kept, Redis flushed) |
| 47 | 06-12 | Admin chart: identical fake expense bars in empty months; hover showed nothing | history months were charged TODAY's DID rent; SVG had no tooltips | 06-12 fresh-start | ⚠ DID rent current-month only; native SVG title tooltips on bars + full-column hover targets + usage-bar title |
| 48 | 06-13 | (bounty C1) confirm_booking with no held token = unguarded double-booking | LLM skips assign_token → zero capacity check; only phone dup guard | 06-13 bounty-r2 | ✅ test_confirm_without_assign_respects_slot_capacity + _token_limit (re-check inside confirm tx) |
| 49 | 06-13 | (bounty H1) Redis flush re-issues token 1 over confirmed DB tokens | token path trusted Redis alone (slot path was already fixed #14) | 06-13 bounty-r2 | ✅ test_token_counter_floored_after_redis_flush |
| 50 | 06-13 | (bounty H2) cancel/reschedule deletes from wrong calendar → ghost events | _do_cancel used branch cal; create used doctor cal | 06-13 bounty-r2 | ⚠ _do_cancel resolves doctor cal then branch fallback (mirror create) |
| 51 | 06-13 | (bounty H3) failed reschedule leaks Redis slot hold until TTL | _do_reschedule used module assign_token; state never set, cleanup blind | 06-13 bounty-r2 | ⚠ _release_hold DECRs on confirm failure (slot keys only) |
| 52 | 06-13 | (bounty H4) solo 4-min call cap unenforced (TD-009 regression) | watchdog lost in LiveKit port; state.plan always "clinic" | 06-13 bounty-r2 | ⚠ org plan → state.plan; asyncio watchdog warns T-10 then closes at cap |
| 53 | 06-13 | (bounty H5) trials never expire → free AI service forever | no trial_pause job; call_blocked ignored trial_ends_at | 06-13 bounty-r2 | ✅ test_call_blocked_expired_trial + daily trial_pause job |
| 54 | 06-13 | (bounty M1) N workers = N schedulers → duplicate calls/writes | every lifespan ran its own APScheduler, plain-SELECT claims | 06-13 bounty-r2 | ⚠ Postgres advisory-lock leader election; only leader schedules |
| 55 | 06-13 | (bounty M2) tasks stranded in_progress after a crash, never retried | status set in_progress then crash; poll only sees pending | 06-13 bounty-r2 | ⚠ requeue_stale_in_progress sweep every 5 min |
| 56 | 06-13 | (bounty M3-M6/L8) walk-in: raw phone, name-blind match, no dup guard, hold leak, past slot, UUID 500 | desk path never got the voice path's guards | 06-13 bounty-r2 | ⚠ normalize_indian_phone + (phone,name) match + dup 409 + guarded DECR + M6 past-slot + L8 400 |
| 57 | 06-13 | (bounty M7) email-OTP failure burns phone OTP → signup dead-end | register only checked verify_code, never is_verified | 06-13 bounty-r2 | ⚠ register accepts verify_code OR is_verified per channel |
| 58 | 06-13 | (bounty M8) prod could echo OTP codes in API response | otp_dev_echo default True, absent from .env.example | 06-13 bounty-r2 | ⚠ otp_echo_enabled forces off when APP_ENV=production; OTP vars added to .env.example |
| 59 | 06-13 | (bounty M9) concurrent same-email register → 500 not 409 | check-then-insert, no IntegrityError handling | 06-13 bounty-r2 | ⚠ register catches IntegrityError → 409 |
| 60 | 06-13 | (bounty M10/L3) leave cascade allowed past dates + unbounded range | only date_from<=date_to validated | 06-13 bounty-r2 | ⚠ reject date_to<branch_today; cap range 365d |
| 61 | 06-13 | (bounty M11) DID format mismatch aborts every inbound call | DID stored verbatim; agent exact-matched | 06-13 bounty-r2 | ✅ test_normalize_did_forms (normalize on write + agent lookup) |
| 62 | 06-13 | (bounty M12) billing month boundary in UTC not IST | hard-block gate + admin overview used UTC month-start | 06-13 bounty-r2 | ⚠ IST month boundary in agent gate + admin overview; IST bucketing |
| 63 | 06-13 | (bounty M13) analytics call-day buckets UTC vs branch-local tokens | func.date on timestamptz truncated in UTC | 06-13 bounty-r2 | ⚠ func.timezone(branch_tz, started_at) for call day/month buckets |
| 64 | 06-13 | (bounty M14) cascade frees DB slots but not Redis keys | cascade never touched Redis; un-leave left slots "full" till TTL | 06-13 bounty-r2 | ⚠ cascade DECRs slot keys for cancelled slot tokens |
| 65 | 06-13 | (bounty M15) backend jobs silently no-op without LiveKit creds; env drift | jobs read os.getenv directly; vars absent from .env.example | 06-13 bounty-r2 | ⚠ config livekit fields + voice_plane_configured + WARNING log; .env.example updated |
| 66 | 06-13 | (bounty L1/L2/L4/L6) rebook stuck in_progress; lost cal-delete silent; doctor card match broken; reminder time read digit-by-digit | various | 06-13 bounty-r2 | ✅ test_telugu_time_spoken; ⚠ unreachable status, enqueue-lost alert, DoctorOut.user_id |
