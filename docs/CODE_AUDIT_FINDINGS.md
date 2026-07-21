# Vachanam Whole-Code Audit and Remediation Record

**Snapshot:** 2026-07-20  
**Scope:** backend, agent, frontend, schemas, migrations, CI/deploy, support
content, and test harness. All 43 confirmed findings in this snapshot were
remediated on 2026-07-20 and are guarded by permanent regression tests.

## Executive Summary

The audit added **56 executable cases**: 51 unit/static behavior contracts and
5 database-backed exploit reproductions. They cover **43 distinct findings**.
Every case now runs as a normal test: there are no expected-failure masks.

The remediation added database uniqueness and session-version controls,
serialized money/trial/calendar races, closed tenant-erasure and anonymous
ticket ownership gaps, centralized WhatsApp entitlement checks, strengthened
DTO validation, isolated CAPTCHA state, corrected frontend/deployment wiring,
and aligned commercial copy with runtime billing behavior.

## Severity Guide

- **High:** can expose tenant data, bypass an entitlement/security boundary, or
  duplicate financial state.
- **Medium:** data integrity, authorization, availability, or material user
  deception under realistic conditions.
- **Low:** deployment coverage, observability, documentation, or UX drift.

## Resolved High Priority Findings

| ID | Finding and evidence | Impact | Required remediation |
| --- | --- | --- | --- |
| AUDIT-001 | `BillingCycle.razorpay_payment_id` has no unique index; `activate_subscription` does select-then-insert. | Concurrent webhook redeliveries can create duplicate paid cycles/renewals. | Add a partial unique constraint for non-null payment IDs and handle `IntegrityError` as an idempotent success. |
| AUDIT-002 | `Branch.google_calendar_id` is guarded only in application code. | Two concurrent settings changes can bypass the collision guard. | Add a database unique constraint/index and normalize calendar IDs. |
| AUDIT-003 | Doctor create/update accepts any `Doctor.google_calendar_id`; it never checks Branch/Doctor ownership across tenants. | Clinic B can write patient booking metadata into Clinic A's Calendar through the shared service account. | Centralize global calendar ownership validation; enforce it for both branch and doctor calendar fields. |
| AUDIT-004 | `_hard_delete_org` deletes tenant models but not `SupportTicket`/`SupportMessage`; FK is `SET NULL`. | A promised DPDP clinic erasure leaves support email, name, phone, subject, and messages. | Decide retention policy; erase or anonymize support records and messages during self-service/admin deletion. |
| AUDIT-005 | Anonymous `/support/chat` compares `str(ticket.org_id or "")`; all public tickets have the same owner key. | Anyone who learns a public ticket UUID can append/reopen that ticket. | Issue a random opaque anonymous-session secret/cookie and require it to reuse a public ticket. |
| AUDIT-006 | `get_current_user` only verifies JWT signature/revocation; staff removal deletes the row without session invalidation. | Removed staff retain branch access until the JWT expires. | Add a user/session version checked on every request, or revoke every active JTI on removal. |
| AUDIT-008 | Password reset replaces only the password then issues a new JWT. | A stolen pre-reset JWT remains valid after account recovery. | Bump a per-user token version/revoke all sessions during reset. |
| AUDIT-022/023 | WhatsApp send helpers call `_send` directly; inbound free text/buttons do not use the received plan. | Lite/Starter clinics can use a Clinic/Multi-only paid capability; unconfigured inbound calls still attempt delivery. | Gate every send and inbound handler with one centralized `wa_enabled(branch, plan)` check. |

## Resolved Medium Priority Findings

| ID | Finding and evidence | Required remediation |
| --- | --- | --- |
| AUDIT-007 | Browser logout clears local storage but never calls `/auth/logout`. | Add a best-effort API logout that revokes the active JTI before local cleanup. |
| AUDIT-009 | A signed JWT missing `sub`, `email`, or `role` raises `KeyError`, producing 500. | Validate all required claims and return 401. |
| AUDIT-010 | Any authorized branch user can run `calendar-test`, which creates/deletes an external Calendar event. | Restrict to `org_admin` and audit the operation. |
| AUDIT-011 | Emergency-loop guard compares raw phone strings; formatting differences bypass it. | Normalize all numbers before storage/comparison, reject invalid data. |
| AUDIT-012–016 | Staff/admin/branch DTOs lack email, length, and phone validation. | Use Pydantic `EmailStr`, explicit max lengths, and shared phone validators. |
| AUDIT-017 | `available_weekdays` accepts invalid/duplicate values. | Enforce unique integers 0–6. |
| AUDIT-018 | Appointment doctors can be created without working hours, duration, or capacity. | Enforce booking-type-specific configuration. |
| AUDIT-019 | PATCH reuses create DTO, requiring `name` and `booking_type`. | Introduce a fully optional `DoctorUpdate` schema. |
| AUDIT-020 | Invited emails are stored without trimming/lowercasing. | Normalize before persistence and match normalized login email. |
| AUDIT-021 | OTP issue records code but endpoint always reports `sent` even if a configured provider failed. | Return a safe 503/retry message; do not claim delivery. |
| AUDIT-024 | WhatsApp picks same-day bookings with `.order_by(Token.date)` only. | Add appointment time, token number, and stable ID ordering. |
| AUDIT-025 | Invoice HTML interpolates clinic name/payment ID without HTML escaping. | Escape all interpolated text in HTML emails. |
| AUDIT-027 | `GST_WAIVED=True`, yet receipts show an `18%` GST line even for zero tax. | Hide the tax row/copy while waived, or charge and present GST consistently. |
| AUDIT-028 | Founding trial cap is explicit count-then-insert. | Serialize with advisory lock/atomic quota table; treat rejected concurrent signup correctly. |
| AUDIT-029 | Two frontend pages derive `today` from UTC `toISOString()`. | Use a local `YYYY-MM-DD` helper or date library using branch/India timezone. |
| AUDIT-030 | Doctor advice follow-up uses host `date.today()` rather than branch-local day. | Derive date with `ZoneInfo(branch.timezone)`. |
| AUDIT-031 | Global Turnstile token/reset slots are overwritten by multiple widgets. | Scope captcha state and request headers to the submitting form/widget. |
| AUDIT-037 | Auth context silently selects `branch_ids[0]` for multi-branch staff. | Implement explicit selected-branch state and a branch chooser. |

## Resolved Low Priority / Release Engineering / Truth Drift

| ID | Finding and evidence | Required remediation |
| --- | --- | --- |
| AUDIT-026 | Invoice label map omits `lite`, rendering `lite plan`. | Add the Lite display label. |
| AUDIT-032 | Vite proxy omits `/patients`, `/treatment`, `/support`, and `/webhooks`. | Add all active API prefixes or use a single API proxy rule. |
| AUDIT-033 | Backend Dockerfile copies backend/alembic but `backend.main` imports `agent.logging_config`. | Copy the required `agent/` package (or extract shared logging). |
| AUDIT-034 | Dependabot targets `main`, repository uses `master`. | Align target branch/default branch policy. |
| AUDIT-035 | ZAP PR trigger targets `main` only. | Include `master` or rename/standardize the branch. |
| AUDIT-036 | WhatsApp settings UI is permanently behind `const WHATSAPP_LIVE = false`. | Use server/runtime feature config and render truthful feature state. |
| AUDIT-038 | Landing says `≈100 call minutes`; source-of-truth trial bucket is 300 minutes (roughly 100 calls). | Say `300 minutes (≈100 calls)`. |
| AUDIT-039 | Login CTA promises a 14-day trial without checking founding slots. | Reuse live founding-slot state or remove unconditional claim. |
| AUDIT-040 | Multi pricing promises CSV exports; no product export route/UI exists. | Implement export or remove the promise. |
| AUDIT-041 | Support KB says Lite allows one doctor; plan source allows three. | Generate docs from plan source or update copy. |
| AUDIT-042 | Support KB says 4-minute calls while runtime solo default is 10 minutes. | Correct documentation and static marketing copy. |
| AUDIT-043 | Support KB promises 18% GST input credit while GST is currently waived. | Align commercial/legal content with billing behavior. |

## Test Infrastructure Remediation

The audit also repaired suite-level reliability problems:

1. PostgreSQL schema DDL is protected by a session advisory lock and starts
   from a clean metadata state, preventing named-enum/create/drop collisions.
2. Pytest's cache plugin is disabled for restricted environments; normal OS
   temporary storage remains available to tests that need `tmp_path`.
3. Redis and the loop-bound rate limiter are reset per test. Onboarding proofs
   that are not throttle tests use the established `testclient` bypass, while
   dedicated rate-limit suites still exercise the real limits.
4. All repository Ruff violations were fixed and
   `asyncio_default_fixture_loop_scope=function` is explicit.

## Verification Results

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_code_audit_regressions.py` | 51 passed |
| `pytest tests/security/test_code_audit_exploits.py` | 5 passed |
| `pytest tests/unit` | 689 passed |
| `pytest tests/security tests/integration` | 539 passed, 3 skipped |
| `pytest tests/edge_cases` | 6 passed |
| repository Ruff (`backend agent tests alembic`) | passed |
| `npm test` | 6 passed |
| `npm run lint` | passed |
| `npm run build` | passed |
| Python compile check (`backend`, migrations) | passed |

## Files Added by This Audit

- `tests/unit/test_code_audit_regressions.py` — 46 repaired-finding contracts
  plus 5 healthy invariants, all permanent gates.
- `tests/security/test_code_audit_exploits.py` — five passing route/DB exploit
  regressions for the highest-risk issues.

## Ongoing Rule

Do not remove or weaken an `AUDIT-*` contract when changing these domains.
Update implementation and tests together, and run the exploit regressions for
calendar ownership, anonymous support ownership, erasure, Calendar probe RBAC,
and deleted-user session invalidation after any auth or tenancy change.
