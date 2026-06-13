# Bug Bounty — Round 4 (fresh sweep, zero-assumptions)

Hunter swept the entire codebase ignoring all prior FIXLOG/TECH_DEBT history and
re-derived every finding from current source. 27 findings.

| # | Severity | Reward | Finding | Disposition |
|---|---|---|---|---|
| F1 | CRITICAL | high | /api/verify-payment unauth + no-op (persists nothing); no Razorpay webhook; trusts client org_id | Already tracked: TD-019 + TD-025 (money/billing phase, needs Vinay) |
| F2 | CRITICAL | high | token-doctor bookings hard-fail without a Google Calendar; wrong per-patient event when set | **FIXED** (FIXLOG 74) |
| F3 | CRITICAL | high | OTP echo leaks code on provider failure in non-prod | **FIXED** (FIXLOG 76) |
| F4 | CRITICAL | high | DID fallback can serve wrong tenant when ≥2 branches | **FIXED** (FIXLOG 75) |
| F5 | CRITICAL | high | slot doctors have no DB backstop for occupancy (Redis + TOCTOU only) | Deferred TD-027 |
| F6 | HIGH | med | call minutes metered only in best-effort shutdown callback | Deferred TD-027 |
| F7 | HIGH | med | JWT 24h vs documented 8h | **FIXED** (FIXLOG 79) |
| F8 | HIGH | med | reschedule confirm requires calendar (same root as F2) | **FIXED** via F2 (FIXLOG 74) |
| F9 | HIGH | med | token capacity counts monotonic issued, not confirmed — cancelled same-day seats unbookable | Deferred TD-026 (fix attempted+reverted: broke capacity invariant) |
| F10 | HIGH | med | walk-in slot DECR unguarded (could decrement another booking's seat) | Non-bug: slot key is an occupancy COUNT (INCR per hold), not an identity sequence — one DECR per failed hold is correct; >0 guard prevents underflow |
| F11 | HIGH | med | number reissue after Redis eviction (reseed from confirmed count) | Deferred TD-027 |
| F12 | HIGH | med | add_staff sets org_id from actor not branch | Non-bug: assert_branch_access already binds branch→actor org |
| F13 | MED | low | assign_token TTL uses naive now() vs branch-tz | Open (minor; same-day key, DB floor compensates) |
| F14 | MED | low | analytics plan lookup uses raw str vs branch_uuid | **FIXED** (FIXLOG 78) |
| F15 | MED | low | find_bookings_by_phone suffix LIKE (unindexed) | Open (perf; branch-scoped, not a leak) |
| F16 | MED | low | calls run unbounded if plan resolution fails / non-solo | **FIXED** (FIXLOG 77) |
| F17 | MED | low | working-hours half-open interval edge | Open (convention; documented) |
| F18 | MED | low | admin overview expensive aggregation under default rate limit | Open (auth-gated) |
| F19 | MED | low | cascade marks unreachable before last attempt outcome known | Intentional L1 tradeoff (kept) |
| F20 | MED | low | reminder job commits mid result-iteration | Open (expire_on_commit=False mitigates) |
| F21 | MED | low | verify_payment audit trusts client org_id | Folds into TD-025 |
| F22 | LOW | low | logout revocation TTL from jwt_expire_hours not real exp | Open (now 8h, bounded) |
| F23 | LOW | low | CSP img-src https: + style-src unsafe-inline | Open |
| F24 | LOW | low | mojibake comments in analytics.py | Open (cosmetic) |
| F25 | LOW | low | requeue_stale create-task can duplicate calendar event | Open (event dup only) |
| F26 | LOW | low | TTS sanitizer leaves stray ASCII symbols | Open |
| F27 | LOW | low | /dev/test Razorpay page public in non-prod | Open |

## Resolution

Fixed this round: F2, F3, F4, F7, F8, F14, F16 (7). Deferred with logged reasons:
F1 (TD-019/025), F5/F6/F11 (TD-027), F9 (TD-026). Non-bugs: F10, F12, F19.
Remaining LOW/MED items (F13, F15, F17, F18, F20–F27) logged here; candidates
for round 5.

Suite after fixes: **384 passed, 2 skipped**.
