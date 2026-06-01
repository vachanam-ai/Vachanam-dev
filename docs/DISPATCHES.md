# Vachanam — Dispatch Log (chronological)

Every `Task(subagent_type=...)` dispatch is appended here. This is the audit trail. Anyone reading the repo cold can trace who did what, when, with which scope, who reviewed it, and which commit landed it.

**Rules:**
- Append entries; never edit older ones (they are historical record)
- Most recent at the bottom (chronological ascending)
- Format defined in `.claude/agents/manager.md`
- Standing rule per CHANGELOG 2026-06-01: **every change is a dispatch.** Orchestrator never embodies a specialist.

---

## Format template

```
## YYYY-MM-DD HH:MM IST — <specialist> dispatched
**Scope:** <one-sentence task summary>
**Inputs:** <files/docs the specialist reads>
**Acceptance:** <how we'll know it's done — pytest cmd, curl, file presence>
**Reviewer:** <named specialist for follow-up review>
**Result:** <DONE / DONE_WITH_CONCERNS / BLOCKED / REJECTED / NEEDS_CONTEXT>
**Files touched:** Created: ... | Modified: ... | Deleted: ...
**Tests:** <pass count or specific test names>
**Commit:** `<hash>` (if work was committed in this dispatch's run)
**Follow-up dispatches:** <next specialist(s) the manager should dispatch>
**Notes:** <anything else worth preserving for retro/audit>
```

---

## Backfill — work completed BEFORE the dispatch rule was set (2026-05-15 through 2026-06-01 mid-day)

The work below was done inline by the orchestrator (main thread) before the mandatory-dispatch rule was logged. This is a known retrospective gap. Each commit hash is included so the full history is recoverable from `git log`. Going forward, every commit must have a corresponding dispatch entry in this file.

| Date range | Phase / Topic | Commits | Files touched (summary) |
|---|---|---|---|
| 2026-05-15 | Phase 0+1 — env, schema, voice agent, booking tools, tests | `a5370a0` through `0fa5d00` | `agent/*`, `backend/models/schema.py`, `tests/unit/*`, `tests/integration/*`, `tests/edge_cases/*` |
| 2026-05-17 | Vobiz SIP credentials reset, Twilio removal | `ed5b333` | `.env`, `backend/config.py`, `CLAUDE.md`, `PHASE_5_PRODUCTION.md` |
| 2026-05-18 | Schema gaps fix, Phase 2 plan draft, infra files | `96f6d92` | `backend/models/schema.py`, `backend/requirements.txt`, `infra/*`, `docs/superpowers/plans/2026-05-18-phase-2-backend.md` |
| 2026-05-22 | Razorpay Standard Checkout | `7f5a184` | `backend/routers/payments.py`, `backend/payments_test_app.py`, `backend/static/index.html`, `backend/static/razorpay-test.html`, `.env` |
| 2026-05-22 | Doc restructure — STATUS/ROADMAP/CHANGELOG/phases/ | `3e4e698` | `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`, `docs/phases/01..10/CLAUDE.md`, `CLAUDE.md` |
| 2026-05-22 | Security & compliance design spec | `df3ea58` | `docs/superpowers/specs/2026-05-22-security-hardening-design.md` |
| 2026-05-29 | Specialist agent roster v1 (8 agents) | `1355cd3` | `.claude/agents/*` (8 files + README) |
| 2026-05-29 | Roster v2 (+database-engineer +brainstormer, Agile, Quality Bar, manager opus, client-accountable) | `88f1fba` | `.claude/agents/manager.md`, `database-engineer.md`, `brainstormer.md`, `AGILE.md`, `QUALITY_BAR.md`, `docs/TECH_DEBT.md` |
| 2026-05-29 | Opus brain for security-engineer, privacy-legal, tester | `9f83232` | `.claude/agents/*.md` (model fields) |
| 2026-05-29 | Full project audit (10-specialist review) | `c8b9a0e` | `docs/audits/2026-05-29-full-project-audit.md`, `docs/TECH_DEBT.md` |
| 2026-05-29 | Fix sprint — TD-007 to TD-013 closed (LLM fallback, aclose, watchdog, N=100 tests, conftest fixes, doc archive) | `c9b0a63` | `agent/agent.py`, `tests/edge_cases/test_concurrent_tokens.py`, `tests/conftest.py`, `docs/_legacy/*` (8 files moved) |
| 2026-05-29 | Pricing decision + landing page UI update (canonical Solo/Clinic/Multi) | `5a711bc` | `backend/static/index.html` |
| 2026-05-29 | Option A approved (MVP-launch posture, Phase 11 deferred) | `a96e9e9` | `docs/phases/11-reliability-hardening/CLAUDE.md`, `docs/STATUS.md`, `docs/CHANGELOG.md` |
| 2026-05-29 | Event-loop binding fixes in booking_tools + conftest | `3143f9d` | `agent/tools/booking_tools.py`, `tests/conftest.py`, `.claude/agents/QUALITY_BAR.md` |
| 2026-06-01 | Phase 4 Task 1 — Alembic migration regenerated | `1b8d06f` | `alembic/versions/ffcf1134aa8f_initial_schema_with_user_table.py` (and deletion of broken 2fe8f201bc31) |
| 2026-06-01 | Phase 4 Tasks 2-5 — init_db, JWT auth, OAuth router, queue router, tests | `4dd5f75` | `backend/database.py`, `backend/middleware/auth_middleware.py`, `branch_guard.py`, `backend/routers/auth.py`, `queue.py`, `tests/unit/test_auth.py`, `tests/edge_cases/test_data_isolation.py` |
| 2026-06-01 | Phase 4 Tasks 6-7 — backend/main.py + retire payments_test_app | `6ffa2d7` | `backend/main.py`, deletion of `backend/payments_test_app.py` |
| 2026-06-01 | Voice call flow spec (brainstorm) | `08d9d5a` | `docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md` |
| 2026-06-01 | Spec tuning — 5s/7s/10s default + unified garbled counter | `5888696` | `docs/superpowers/specs/2026-06-01-voice-call-flow-latency-design.md` |
| 2026-06-01 | Voice call flow implementation — 12 components, 77/77 tests | `7adbbde` | `agent/services/silence_handler.py`, `agent/services/audio_quality.py`, `scripts/generate_clinic_greeting.py`, `tests/unit/test_silence_handler.py`, `tests/unit/test_audio_quality.py`, `agent/agent.py` (rewrite), `agent/prompts/system_prompt.py`, `agent/requirements.txt` |

**Total commits before rule:** 22 across ~3 weeks. All work done inline by orchestrator. Going forward, the same throughput must produce ~22 dispatch entries (or proportional) instead.

---

## Dispatch entries (after rule, 2026-06-01 onward)

*(First dispatch entry will be Phase 4.5 sprint planning via manager.)*
