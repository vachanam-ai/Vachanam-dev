# Bug Bounty — Round 5 (iteration 2, fresh sweep)

Hunter re-audited from current source, ignoring all history, concentrating on
the easy-to-overlook surface: frontend, jobs, middleware, services, migrations,
schema, concurrency. 17 findings.

| # | Severity | Reward | Finding | Disposition |
|---|---|---|---|---|
| G1 | CRITICAL | high | payments endpoints unauthenticated; amount + audit org_id attacker-controlled | TD-025 (+ TD-019) — billing/auth phase, money decision (Vinay) |
| G2 | HIGH | high | no payment ever activates a subscription; no Razorpay webhook | TD-019 — billing phase |
| G3 | HIGH | med | reminder flag set+committed before dispatch → lost on crash | Open (design-accepted; mirror requeue sweep later) |
| G4 | HIGH | med | slot doctors have no DB exclusion backstop (Redis + TOCTOU only) | TD-027 (already logged) |
| G5 | HIGH | med | doctor-role staff login never linked to a Doctor row (orphan) | **FIXED** (FIXLOG 80) |
| G6 | MED | low | staff/doctor passwords accepted weak/all-numeric | **FIXED** (FIXLOG 81) |
| G7 | MED | low | logout revocation TTL uses fixed 8h not real exp | Open (over-revokes = fail-safe; minor Redis bloat) |
| G8 | MED | low | multiple default doctors → non-deterministic routing | **FIXED** (FIXLOG 82) |
| G9 | MED | low | DID change leaves old number on the LiveKit trunk | **FIXED** (FIXLOG 83) |
| G10 | MED | low | calendar_writer create/update don't use _resolve_calendar_id | Open — verify; create/update payloads currently carry calendar_id |
| G11 | MED | low | requeue_stale create can duplicate a calendar event on crash | Open (F25/TD — idempotency key; event dup only) |
| G12 | MED | low | create-order reflects raw Razorpay error | **FIXED** (FIXLOG 84) |
| G13 | MED | low | confirmed_at naive utcnow into tz column | **FIXED** (FIXLOG 85) |
| G14 | MED | low | find_bookings_by_phone last10 LIKE → intra-tenant bleed | Open (F15; needs normalized-phone exact match) |
| G15 | LOW | low | CSP img-src https: + style-src unsafe-inline | Open |
| G16 | LOW | low | /request-otp no per-destination throttle (SMS-bomb) | **FIXED** (FIXLOG 86) |
| G17 | LOW | low | over-long walk-in free-text → 500 not 422 | **FIXED** (FIXLOG 87) |

## Resolution

Fixed this round: G5, G6, G8, G9, G12, G13, G16, G17 (8). Deferred with logged
reasons: G1/G2 (TD-019/025, money/billing phase), G4 (TD-027). Open lower-value:
G3, G7, G10, G11, G14, G15 — candidates for round 6. The hunter independently
confirmed the round-4 hardening (token races, DID fallback, OTP fail-closed,
leader election, trial pause, tenant isolation, linear migration chain) is
genuinely present and holds.

Suite after fixes: **392 passed, 2 skipped**.
