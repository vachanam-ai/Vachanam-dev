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
