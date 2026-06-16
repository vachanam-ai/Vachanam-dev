# Vachanam — Project Structure (live doc)

**Source of truth for what exists in the repo, where it lives, and what state it is in.** Auto-updated by every dispatch that adds/renames/deletes a tracked file under `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`, or `docs/`. Stale entries are a merge blocker — `manager` rejects the merge checklist when this file does not match `git ls-files`.

**Last verified against `git ls-files`:** 2026-06-04 (after Phase 4.5 Tasks 11+13 — docs/legal/ + docs/runbooks/ expanded)

---

## Section 1 — Purpose and rules

This file answers three questions in one place:

1. **What exists?** Every tracked source/test/doc file and its purpose.
2. **What state is it in?** Status legend below.
3. **Who owns it?** Specialist domain mapping.

Anyone reading the repo cold can find the right file and know whether it is real, half-built, or aspirational. Anyone planning a sprint can see what is already shipped vs what is still placeholder.

### Status legend

| Status | Meaning |
|---|---|
| placeholder | Directory or __init__.py / stub exists; no real implementation. |
| scaffolded | Code present but not wired into the app yet (imports compile, no runtime path hits it). |
| working | Wired in and runs end-to-end manually. No automated test coverage yet OR tests not yet exhaustive. |
| tested | Has pytest coverage that passes; integration behavior verified against real services where applicable. |
| deployed | Tested AND running in a real environment (staging or production). |
| archived | Moved to docs/_legacy/ or otherwise retired; historical reference only. |

### Update rule (also in QUALITY_BAR.md + AGILE.md DoD + manager merge checklist)

Every dispatch that adds, renames, or deletes a tracked file under `agent/`, `backend/`, `frontend/`, `infra/`, `tests/`, `scripts/`, `alembic/`, or `docs/` updates this file in the same commit. Status column reflects reality after the dispatch lands. Stale file = `manager` rejects merge.

---

## Section 2 — Top-level layout

```
vachanam/
|-- CLAUDE.md                  master context (the law)
|-- .env.example               all 26 required env vars (empty values)
|-- .env                       NEVER COMMITTED (local secrets)
|-- .gitignore
|-- .gitleaks.toml             gitleaks config — default OSS ruleset + allowlist for test fixtures
|-- docker-compose.yml         local Postgres 16 + Redis 7 for dev
|-- alembic.ini                Alembic config (URL from settings)
|-- pytest.ini                 pytest discovery config
|
|-- .github/
|   |-- workflows/
|   |   `-- ci.yml             CI: test job (PG16+Redis7+pytest, Python 3.11) + secret-scan (gitleaks)
|   `-- dependabot.yml         weekly pip (backend+agent) + npm (frontend, future-proof) + github-actions updates
|
|-- .claude/agents/            10 specialist personas + AGILE + QUALITY_BAR + README
|-- agent/                     voice agent (LiveKit + Sarvam + Gemini) — runs on Fly.io bom
|-- backend/                   FastAPI app — runs on Render
|-- frontend/                  React + Vite PWA — runs on Cloudflare Pages (NOT YET BUILT)
|-- infra/                     Dockerfiles + Fly/Render configs
|-- alembic/                   schema migrations
|-- scripts/                   one-off operational scripts
|-- tests/                     pytest suites (unit / integration / edge_cases / security)
`-- docs/                      ROADMAP, STATUS, CHANGELOG, TECH_DEBT, DISPATCHES, phases, specs
```

Status: `working` for backend / agent / tests / docs; `placeholder` for frontend; `scaffolded` for scripts.

---

## Section 3 — Voice agent (`agent/`)

Owner: `voice-agent-engineer`. Runs on Fly.io Mumbai. Connects to LiveKit + Sarvam STT/TTS + Gemini (fallback GPT-4o-mini) + Vobiz SIP trunk. Booking tools call backend HTTP API.

| Path | Status | Purpose |
|---|---|---|
| `agent/__init__.py` | placeholder | Package marker. |
| `agent/bot.py` | working (live calls tested) | Pipecat 1.3.0 pipeline: Sarvam Saaras STT + Gemini 2.5 Flash (GPT-4o-mini fallback) + Sarvam Bulbul TTS (kavitha, Telugu script). Tool registration, token-rollback-on-disconnect, intent-based human transfer. Replaced `agent/agent.py` (LiveKit entrypoint, deleted). |
| `agent/server.py` | working | FastAPI WS transport for Vobiz: `/answer` XML (inbound + outbound), `/ws` Pipecat bridge, transfer signal map, recording callback (testing-only). |
| `agent/vobiz_minimal/` | frozen baseline | From-scratch Pipecat+Vobiz connector used to debug transport; reference only. |
| `agent/livekit_minimal/` | working (in+out) | Live LiveKit voice agent: SIP trunks + dispatch rule, agent worker. |
| `agent/session_state.py` | working | Per-call state dataclass (branch_id, doctor_id, token_held, token_redis_key, language, etc.). |
| `agent/requirements.txt` | working | Voice-agent Python pins (livekit-agents 1.5.9, livekit-plugins-sarvam, turn-detector, google-genai, openai, structlog, tenacity, asyncpg, redis). |
| `agent/prompts/__init__.py` | placeholder | Package marker. |
| `agent/prompts/system_prompt.py` | working | Telugu / Hindi / English system-prompt builder with WAIT REQUESTS, SILENCE PROMPTS, GARBLED INPUT sections. LLM handles wait semantically via prompt (no keyword detection). |
| `agent/services/__init__.py` | placeholder | Package marker. |
| `agent/services/tts_sanitizer.py` | tested (11/11) | Strip markdown, expand digit spacing, normalize for Bulbul TTS. RULE 6 — every `session.say()` goes through this. |
| `agent/services/calendar_proxy.py` | working | Re-export shim of `backend/services/calendar_service.py` for the agent runtime (wired into `register_tools` in bot.py). |
| `agent/services/meta_stub.py` | working | No-op WhatsApp `MetaService` stub (real impl = MVP2). Logs masked phone, never blocks booking. |
| `agent/tools/__init__.py` | placeholder | Package marker. |
| `agent/tools/booking_tools.py` | working | 4 LLM function tools: `route_to_doctor`, `check_availability`, `assign_token` (Redis INCR), `confirm_booking`. RULE 3 — token released on disconnect if not confirmed. |

**Open debt touching this dir:** TD-005 (romanized `padipoyadu` vs Telugu script), TD-020 (pre-cached greeting WAV not published via LiveKit track-publish API), TD-021 (STT confidence Layer A).

---

## Section 4 — Backend (`backend/`)

Owner: `backend-engineer` (routes, services, jobs), `database-engineer` (`models/schema.py`, alembic), `security-engineer` (`middleware/auth_middleware.py`, `middleware/security_headers.py`, future `middleware/rate_limit.py`). Runs on Render. FastAPI + SQLAlchemy 2.x async + asyncpg + Pydantic.

### 4.1 - App root

| Path | Status | Purpose |
|---|---|---|
| `backend/__init__.py` | placeholder | Package marker. |
| `backend/main.py` | working | FastAPI app factory. CORS allowlist (exact origins, `allow_credentials=True`), `SecurityHeadersMiddleware`, routers (auth, queue, payments), static landing mount, `/health`, prod-disabled `/docs` / `/redoc` / `/openapi.json` via `_is_prod`. |
| `backend/config.py` | working | Pydantic `Settings` — all 26 env vars typed + `app_env`, `frontend_url`, `redis_url`, `database_url`. Added `rate_limit_bypass_ips` (Phase 4.5 Task 5). |
| `backend/database.py` | working | Async SQLAlchemy engine + `AsyncSessionLocal` per-call factory + `init_db()` helper. **No module-level session singletons** (per QUALITY_BAR; see TD-016/TD-017 closed). |
| `backend/requirements.txt` | working | Backend Python pins (fastapi, uvicorn, sqlalchemy, asyncpg, alembic, pydantic-settings, structlog, tenacity, redis, razorpay, google-auth, httpx, fastapi-limiter — added Phase 4.5). |

### 4.2 - Models

| Path | Status | Purpose |
|---|---|---|
| `backend/models/__init__.py` | placeholder | Package marker. |
| `backend/models/schema.py` | working | 11 tables: Org, Branch, Doctor, Patient, Token, Call, FollowupTask, BillingCycle, WhatsAppSession, User, audit_log (NEW Phase 4.5 Task 2). All multi-tenant tables have `branch_id` FK. UUID PKs. JSONB. Explicit FK `ondelete=` (TD-019 closed). FK-only indexes (TD-018 partially closed; compound indexes deferred to Phase 5). |

### 4.3 - Routers

| Path | Status | Purpose |
|---|---|---|
| `backend/routers/__init__.py` | placeholder | Package marker. |
| `backend/routers/auth.py` | tested | `POST /auth/google` (Google ID-token exchange -> JWT), `GET /auth/me`, `POST /auth/logout`. Rate-limited (5/min, 100/min). IP blocklist. Audit: `user.login.success` + `user.login.failure` (direct `write_audit_row` calls; spec §8.2 email exception applied to failure). **TD-026 open:** user-not-found path (valid Google token, email not in DB → 403) does not write audit row yet. |
| `backend/routers/payments.py` | tested | Razorpay Standard Checkout — `POST /api/create-order`, `POST /api/verify-payment`. Audit: `payment.verify.success` + `payment.verify.fail` (direct `write_audit_row` calls; fail fires BEFORE raising 400). |
| `backend/routers/queue.py` | tested | `GET /queue/{branch_id}/today`, `PATCH .../attend`, `PATCH .../no-show`. JWT-protected + `branch_guard`. Audit: `@audit("token.attend", resource_type="token")` + `@audit("token.no_show", ...)` decorators; resource_id/user_id/branch_id set on request.state inside handler. |
| `backend/routers/admin.py` | tested | `GET /admin/ping` gated by `require_admin` (is_admin=True JWT claim) + `default_limit`. Placeholder skeleton for Phase 8 admin dashboard routes (spec §8.1 admin.view_* actions). Returns `{"status": "ok", "admin_user_id": ...}`. Non-admin → 403; no JWT → 401; expired JWT → 401. |

**Not yet created (Phase 5+):** `routers/whatsapp.py`, `routers/dashboard.py`, `routers/onboarding.py`.

### 4.4 - Middleware

| Path | Status | Purpose |
|---|---|---|
| `backend/middleware/__init__.py` | placeholder | Package marker. |
| `backend/middleware/auth_middleware.py` | working | JWT validation, request-scoped `current_user`. |
| `backend/middleware/branch_guard.py` | working | RULE 1 enforcement — every request scoped to the user's branch_id. |
| `backend/middleware/security_headers.py` | working | CSP (script-src self + Razorpay + Google; style-src self unsafe-inline for Google Fonts), HSTS `max-age=31536000; includeSubDomains` (no `preload` until Phase 10), X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy. Registered AFTER CORSMiddleware so it runs on preflights too. Reviewed by security-engineer 2026-06-02 (commit `6b00686`). |

| `backend/middleware/rate_limit.py` | tested (13/13) | Phase 4.5 Task 5. pyrate-limiter Redis-backed sliding window. Named per-endpoint limiters (`auth_google_limit` 5/min, `queue_today_limit` 60/min, etc.). JWT-sub keyed when Bearer present, IP keyed otherwise. Trusted-IP bypass via `RATE_LIMIT_BYPASS_IPS` env. IP blocklist helpers (`record_failed_login`, `is_ip_blocked`, `check_ip_blocklist`). All 13 tests GREEN. |

### 4.5 - Services / Jobs

| Path | Status | Purpose |
|---|---|---|
| `backend/services/__init__.py` | placeholder | Package marker. |
| `backend/services/audit_service.py` | tested (22/22) | Phase 4.5 Task 7. `PII_DENYLIST` constant, `write_audit_row()` async INSERT helper (PII-validates metadata before DB write; swallows DB errors per spec §8.5), `@audit` decorator factory (sets audit context from request.state; catches all audit errors; never blocks user response). TD-022 closed. |
| `backend/jobs/__init__.py` | placeholder | Package marker. |

**Not yet created (Phase 5+):** `services/token_service.py`, `services/calendar_service.py`, `services/meta_service.py`, `services/whatsapp_agent.py`, `services/doctor_commands.py`, `services/cancel_day_bookings.py`, `services/vobiz_partner.py`, `services/onboarding_service.py`. Jobs: `token_expiry.py`, `eod_summary.py`, `followup_calls.py`, `pre_appt_reminder.py`, `billing_cycle.py`, `trial_expiry.py`.

### 4.6 - Static

| Path | Status | Purpose |
|---|---|---|
| `backend/static/index.html` | working | 1:1 mirror of `vachanam.in` landing page used as Razorpay test target. **TD-024 open:** inline script tag line 852 violates new CSP `script-src`. Phase 4.5 Task 9 or Phase 5 to extract. |
| `backend/static/razorpay-test.html` | working | Standalone Razorpay test page. **TD-024 open:** inline onclick handler (line 72) + script tag (line 83). |
| `backend/static/greetings/.gitkeep` | placeholder | Directory marker for per-branch greeting WAVs generated by `scripts/generate_clinic_greeting.py`. WAVs themselves are gitignored. |

---

## Section 5 — Frontend (`frontend/`)

Owner: `frontend-engineer`. Target: React + Vite PWA on Cloudflare Pages.

**Status: placeholder.** Directory + `public/` + `src/` exist but contain no tracked files. Built in Phase 7 (Receptionist PWA) and Phase 8 (Owner + Admin dashboards). See `docs/phases/07-frontend-receptionist/CLAUDE.md` + `docs/phases/08-frontend-dashboards/CLAUDE.md`.

Planned layout (will be created in Phase 7+):

```
frontend/
|-- package.json
|-- vite.config.js
|-- tailwind.config.js
|-- public/manifest.json
`-- src/
    |-- main.jsx, App.jsx
    |-- api/client.js                (axios + JWT interceptor)
    |-- hooks/{useAuth,useQueue,useDashboard}.js
    |-- pages/{Login,Queue,WalkIn,Dashboard,AdminDashboard}.jsx
    `-- components/{PatientCard,HeroNumber,WeeklyChart,OfflineBanner}.jsx
```

---

## Section 6 — Infra (`infra/`) and CI (`github/`)

Owner: `devops-engineer`.

### 6.1 - Infra configs

| Path | Status | Purpose |
|---|---|---|
| `infra/Dockerfile.agent` | working | Voice-agent container (Fly.io bom Mumbai). **TD-014 open:** runs as root; fix before Phase 10. |
| `infra/Dockerfile.backend` | working | Backend container (Render or local). **TD-014 open:** runs as root. |
| `infra/fly.agent.toml` | scaffolded | Fly.io deploy config; not yet flown to production. |
| `infra/render.yaml` | scaffolded | Render deploy config; not yet deployed. |

### 6.2 - GitHub CI / secret-scan / Dependabot

| Path | Status | Purpose |
|---|---|---|
| `.github/workflows/ci.yml` | working | Two-job workflow triggered on PR + push to main/master. Job 1 `test`: Python 3.11, Postgres 16 service, Redis 7 service, installs backend + agent deps, runs `alembic upgrade head`, runs `pytest tests/ -v --tb=short`. Job 2 `secret-scan`: full git history checkout + gitleaks OSS scan. **TD-015 closed.** |
| `.github/dependabot.yml` | working | Weekly (Monday 06:00 UTC) security updates for: `pip` root scan (backend), `pip /agent` scan (agent), `npm /frontend` (future-proof for Phase 7), `github-actions`. Max 5 open PRs per ecosystem. Labels auto-applied. |
| `.gitleaks.toml` | working | Gitleaks configuration. Extends default OSS ruleset. Allowlist: test fixture phone numbers (+919999999999 etc.), ci.yml test JWT secret, test-prefixed API key stubs, .env.example empty-value lines, docs/*.md example key patterns. |

### 6.3 - Runbooks

| Path | Status | Purpose |
|---|---|---|
| `docs/runbooks/cloudflare-setup.md` | working | Phase 10 cutover doc (~80 lines). DNS records for all subdomains, TLS Full Strict setup, HSTS config, Managed Rules (OWASP CRS unlimited on Free), Bot Fight Mode, 5 custom firewall rules (.env / .git / wp-admin / wp-login / .DS_Store blocks), Free-tier quota clarification (WAF RL 10k cap does NOT apply to managed CRS), Phase 10 cutover sequence, Under Attack 1-pager. |
| `docs/runbooks/breach-response.md` | working | Phase 4.5 Task 13a. 5-step breach response (detect, contain, assess, notify, remediate) + 6 pre-rehearsed scenarios (JWT leak, account compromise, DB access leak, webhook secret leak, audit tamper, cross-tenant leak). Concrete containment commands per scenario. 72h DPB notification + 24h clinic notification. Drill schedule. Notification email templates. |
| `docs/runbooks/dsar.md` | working | Phase 4.5 Task 13b. 7-step DSAR flow: receive, verify identity, acknowledge (48h), execute (4 request types: access/correct/delete/withdraw), respond (7-day SLA), audit log entry, retain record (3 years). Manual SQL fallback for MVP1; automated script placeholder for Phase 6+. |

### 6.4 - Legal documents

Owner: `privacy-legal`. Hosted at `app.vachanam.in/privacy` and `/terms` (backend Task 12 serves rendered versions).

| Path | Status | Purpose |
|---|---|---|
| `docs/legal/privacy-policy.md` | working | Phase 4.5 Task 11a. 12 sections per spec section 9.2. Plain English, DPDP-defensible. Reflects no-recording decision (Option A). Lists 11 third-party processors with data locations. 7 retention periods with enforcement commitment. Contact: privacy@vachanam.in. |
| `docs/legal/terms-of-service.md` | working | Phase 4.5 Task 11b. Clinic-facing SaaS terms (10 sections). Service description, clinic obligations as Data Fiduciary, Vachanam obligations as Data Processor, subscription plans (Solo/Clinic/Multi), acceptable use, limitation of liability, governing law (Hyderabad). |
| `docs/legal/data-processing-agreement.md` | working | Phase 4.5 Task 11c. DPA template (12 sections). Vachanam = Data Processor, Clinic = Data Fiduciary. Sub-processor list (12 vendors). Security measures table. 24h breach notification to Clinic. Audit rights (once/year). Data return + deletion on termination (30 days). Signature block. |

---

## Section 7 — Alembic (`alembic/`)

Owner: `database-engineer`.

| Path | Status | Purpose |
|---|---|---|
| `alembic/README` | working | Auto-generated readme. |
| `alembic/env.py` | working | Loads URL from `backend/config.Settings` (TD-011 closed). |
| `alembic/script.py.mako` | working | Migration template. |
| `alembic/versions/ffcf1134aa8f_initial_schema_with_user_table.py` | working | Initial schema — 10 tables. Phase 4 (replaces orphan 2fe8f201bc31). |
| `alembic/versions/8559268c0c44_phase45_audit_log_ondelete_fk_indexes.py` | working | Phase 4.5 Task 2 — adds `audit_log` table, sets explicit FK `ondelete=` (TD-019 closed), FK-only indexes (TD-018 narrowed scope). Reviewed; commit `be6d76e`. |

**Open debt:** TD-022 (audit_log.metadata_json PII denylist enforcement — must ship with `@audit` decorator in Phase 4.5 Task 7), TD-023 (`GRANT INSERT, SELECT ON audit_log` + `REVOKE UPDATE, DELETE` — Phase 10 prod-init SQL).

---

## Section 8 — Scripts (`scripts/`)

| Path | Status | Purpose |
|---|---|---|
| `scripts/generate_clinic_greeting.py` | scaffolded | Offline Sarvam Bulbul script to pre-generate per-branch greeting WAVs into `backend/static/greetings/`. Not wired into LiveKit publish path yet (TD-020 — Phase 10). |

---

## Section 9 — Tests (`tests/`) and Docs (`docs/`)

### 9.1 - Tests

Owner: `tester` (writes), implementer-specialists (do not write tests for their own code).

| Path | Status | Purpose |
|---|---|---|
| `tests/conftest.py` | working | Real Postgres + real Redis fixtures (no fakeredis, no SQLite). Uses `settings.redis_url`. Pre-flushes Redis. (TD-011 + TD-012 closed.) |
| `tests/__init__.py` | placeholder | Package marker. |
| `tests/unit/__init__.py` | placeholder | Package marker. |
| `tests/unit/test_tts_sanitizer.py` | tested (11/11) | TTS sanitization rules. |
| `tests/unit/test_bot_pipeline_builder.py`, `test_bot_tools_and_fallback.py`, `test_bot_tts_sanitizer.py`, `test_pipecat_imports.py` | tested | Pipecat bot pipeline, tool registration, LLM fallback, sanitizer wiring. (Replaced LiveKit-era test_emergency/test_silence_handler/test_audio_quality — modules deleted with the Pipecat rewrite.) |
| `tests/unit/test_auth.py` | tested (6/6) | JWT + Google OAuth verification. |
| `tests/integration/__init__.py` | placeholder | Package marker. |
| `tests/integration/test_booking_flow.py` | tested (4/4) | Full booking happy path against real DB + real Redis. |
| `tests/edge_cases/__init__.py` | placeholder | Package marker. |
| `tests/edge_cases/test_concurrent_tokens.py` | tested (2/2) | RULE 2 — N=100 concurrent callers all get distinct tokens (TD-010 closed). |
| `tests/edge_cases/test_data_isolation.py` | tested (3/3) | RULE 1 — cross-org `branch_id` leak attempts blocked. |
| `tests/security/__init__.py` | working | Phase 4.5 Task 4 security tests package. |
| `tests/security/test_rate_limit.py` | tested (13/13) | Phase 4.5 Task 5. All rate-limit tests GREEN. Fixed 2 tester bugs: (1) ASGITransport fixture now explicitly sets `client=("testclient", 123)` since httpx default is `("127.0.0.1", 123)` not `"testclient"`, (2) IP-blocklist test now sets fake `GOOGLE_OAUTH_CLIENT_ID` via monkeypatch so requests reach the real Google verification path (which triggers `record_failed_login`) instead of hitting the "OAuth not configured" early-return. |
| `tests/security/test_audit_log.py` | tested (21/21 + 1 SKIP) | Phase 4.5 Task 7. All 21 runnable tests GREEN. 1 skip = `test_db_role_cannot_update_or_delete_audit_log` (deferred to Phase 10 prod-init per TD-023). TD-022 closed. |
| `tests/security/test_headers.py` | tested (7/7) | Phase 4.5 Task 8. HTTP security headers presence + value checks. |
| `tests/security/test_cors.py` | tested (5/5) | Phase 4.5 Task 8. CORS policy exact-origin allowlist enforcement. |
| `tests/security/test_admin_only.py` | tested (4/4) | Phase 4.5 Task 9. require_admin enforcement on GET /admin/ping: non-admin → 403, admin → 200, no JWT → 401, expired → 401. All 4 GREEN after admin.py created + registered. |
| `tests/security/test_jwt.py` | tested (5/5) | Phase 4.5 Task 8. JWT edge cases (expiry, revocation, malformed). |
| `tests/security/test_secrets_not_in_repo.py` | tested (1/1) | Phase 4.5 Task 16. Scans `git log --all -p` for 6 secret patterns (rzp_live_, sk-proj-, AIza..., JWT_SECRET=, META_ACCESS_TOKEN=, RAZORPAY_KEY_SECRET=). Allowlist mirrors .gitleaks.toml. Asserts zero real matches. |

**Baseline (2026-06-04, Task 16):** `pytest tests/ -v` -> 133/133 pass + 1 skip against Docker Postgres 16 + Redis 7 + Python 3.14. Added 1/1 test_secrets_not_in_repo.py. Prior baseline (Task 9): 132/132 pass + 1 skip.

### 9.2 - Docs

| Path | Status | Purpose |
|---|---|---|
| `docs/STATUS.md` | working | Single source of truth — current phase, what is done, what is broken, what is next. |
| `docs/ROADMAP.md` | working | 11 phases + dependency graph. |
| `docs/CHANGELOG.md` | working | Session-by-session decision log (append-only). |
| `docs/TECH_DEBT.md` | working | Shortcut ledger — TD-005, 014, 018, 020, 021, 023, 024, 025, 026, 027, 028 open; TD-015, 019, 022 closed. |
| `docs/DISPATCHES.md` | working | Chronological dispatch audit trail (append-only). |
| `docs/PROJECT_STRUCTURE.md` | working | **This file.** Live repo map. |
| `docs/phases/01-foundation/CLAUDE.md` | working | DONE. |
| `docs/phases/02-voice-agent/CLAUDE.md` | working | DONE. |
| `docs/phases/03-razorpay-checkout/CLAUDE.md` | working | DONE. |
| `docs/phases/04-backend-core/CLAUDE.md` | working | DONE (2026-06-01). |
| `docs/phases/05-whatsapp/CLAUDE.md` | scaffolded | Future phase doc. |
| `docs/phases/06-jobs-calendar/CLAUDE.md` | scaffolded | Future phase doc. |
| `docs/phases/07-frontend-receptionist/CLAUDE.md` | scaffolded | Future phase doc. |
| `docs/phases/08-frontend-dashboards/CLAUDE.md` | scaffolded | Future phase doc. |
| `docs/phases/09-subscriptions-onboarding/CLAUDE.md` | scaffolded | Future phase doc. |
| `docs/phases/10-deployment/CLAUDE.md` | scaffolded | Future phase doc. |
| `docs/phases/11-reliability-hardening/CLAUDE.md` | scaffolded | DEFERRED — post-launch placeholder. |
| `docs/superpowers/specs/2026-05-22-security-hardening-design.md` | working | Phase 4.5 spec; section 16 REVISIONS appended for fastapi-limiter + Cloudflare WAF + Render TLS corrections. |
| `docs/db/migration-log.md` | working | Migration-by-migration narrative. |
| `docs/MAIN_AGENDA.md` | working | One-page project highlight — what Vachanam is, who it serves, runtime flow, stack, current state, graphify findings. Created 2026-06-03. |
| `docs/compliance/dpdp-gap-analysis-2026-06-04.md` | working | DPDP gap analysis comparing GPT's 13-point framework against our security spec. 9 sections: coverage matrix, confirmed items, MVP1 gaps, MVP2 gaps, out-of-scope corrections, ranked next-actions, spec amendments, launch checklist, DPDP Rules status note. Created 2026-06-04. |
| `.claude/agents/README.md` | working | Roster overview. |
| `.claude/agents/AGILE.md` | working | Sprint cadence + DoR + DoD + caveman-narrow scope. |
| `.claude/agents/QUALITY_BAR.md` | working | Senior-dev standards + process rules (mandatory dispatch + caveman-narrow + PROJECT_STRUCTURE live doc). |
| `.claude/agents/manager.md` | working | Stubborn client-accountable coordinator. Model pinned `claude-opus-4-6`. |
| `.claude/agents/brainstormer.md` | working | Tech-lead. Model pinned `claude-opus-4-6`. |
| `.claude/agents/security-engineer.md` | working | Model pinned `claude-opus-4-6`. |
| `.claude/agents/privacy-legal.md` | working | Model pinned `claude-opus-4-6`. |
| `.claude/agents/tester.md` | working | Model pinned `claude-opus-4-6`. |
| `.claude/agents/backend-engineer.md` | working | Model: `sonnet`. |
| `.claude/agents/frontend-engineer.md` | working | Model: `sonnet`. |
| `.claude/agents/voice-agent-engineer.md` | working | Model: `sonnet`. |
| `.claude/agents/database-engineer.md` | working | Model: `sonnet`. |
| `.claude/agents/devops-engineer.md` | working | Model: `sonnet`. |

---

## Cross-references

- Root law: [`CLAUDE.md`](../CLAUDE.md) — 10 absolute rules, full env-var list, pricing, costs, stack.
- Current state: [`docs/STATUS.md`](STATUS.md).
- Phase plan: [`docs/ROADMAP.md`](ROADMAP.md).
- Decision history: [`docs/CHANGELOG.md`](CHANGELOG.md).
- Shortcut ledger: [`docs/TECH_DEBT.md`](TECH_DEBT.md).
- Dispatch audit trail: [`docs/DISPATCHES.md`](DISPATCHES.md).
- Quality gate: [`.claude/agents/QUALITY_BAR.md`](../.claude/agents/QUALITY_BAR.md).
- Sprint cadence: [`.claude/agents/AGILE.md`](../.claude/agents/AGILE.md).
