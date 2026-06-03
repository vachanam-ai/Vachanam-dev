# Vachanam — Roadmap

10 phases. Each is independently testable. Conquer one at a time. Don't start a phase until its prerequisites are done.

---

## Dependency graph

```
Phase 1  Foundation ─────┐
                         ├──► Phase 2  Voice agent ──┐
                         │                           │
                         └──► Phase 3  Razorpay ─────┤
                                                     │
                              Phase 4  Backend core ◄┘ (needs 1,2,3)
                                       │
                                       ▼
                              Phase 4.5  Security & compliance
                                       │
                ┌──────────────────────┼────────────────┐
                │                      │                │
                ▼                      ▼                ▼
  [MVP2] Phase 5 WhatsApp    Phase 6 Jobs+Cal     Phase 7 PWA receptionist
         (DEFERRED)          (reduced: Cal +           │
                │             token expiry)             │
                │                      │                │
                │              ┌───────┴────────────────┘
                │              │
                │              ▼
                │       Phase 8 Owner + Admin dashboards
                │              │
                │              ▼
                │       Phase 9 Subscriptions + Onboarding
                │              │      (email reminders, not WA)
                │              ▼
                │       Phase 10 Deployment (MVP1 SHIPS HERE)
                │
                └──────► MVP2 starts after first paying clinic
```

---

## Phases at a glance

| # | Name | Status | Days | Unlocks | Doc |
|---|---|---|---|---|---|
| 1 | Foundation (env, DB schema, alembic, docker) | ✅ DONE | — | everything | [01-foundation/](phases/01-foundation/CLAUDE.md) |
| 2 | Voice agent (LiveKit + Sarvam + Gemini + 4 tools) | ✅ DONE | — | inbound calls (once telephony live) | [02-voice-agent/](phases/02-voice-agent/CLAUDE.md) |
| 3 | Razorpay Standard Checkout (one-time) | ✅ DONE | — | paid signup flow | [03-razorpay-checkout/](phases/03-razorpay-checkout/CLAUDE.md) |
| 4 | Backend core (main.py, JWT auth, queue API) | 🔨 NEXT | 1-2 | every backend route | [04-backend-core/](phases/04-backend-core/CLAUDE.md) |
| 4.5 | Security & compliance (CSP, rate limit, audit log, privacy policy, DPDP) | 📋 SPEC DONE | 3-4 | safe Phase 5+ | [spec](superpowers/specs/2026-05-22-security-hardening-design.md) |
| 5 | WhatsApp (Meta webhook, doctor cmds, patient FSM) | 🅿️ DEFERRED-MVP2 | 3-4 | WA channel (MVP2 only) | [05-whatsapp/](phases/05-whatsapp/CLAUDE.md) |
| 6 | Jobs + Calendar (Google Cal + token expiry; WA jobs → MVP2) | ⬜ | 1 | calendar events, token cleanup | [06-jobs-calendar/](phases/06-jobs-calendar/CLAUDE.md) |
| 7 | Receptionist PWA (React + Vite, queue UI) | ⬜ | 3-4 | staff use clinic | [07-frontend-receptionist/](phases/07-frontend-receptionist/CLAUDE.md) |
| 8 | Owner + Admin dashboards | ⬜ | 3 | analytics + Vinay's P&L | [08-frontend-dashboards/](phases/08-frontend-dashboards/CLAUDE.md) |
| 9 | Subscriptions + Onboarding (Razorpay subs + Vobiz DID; email reminders, not WA) | ⬜ | 3-4 | sell to first paying clinic | [09-subscriptions-onboarding/](phases/09-subscriptions-onboarding/CLAUDE.md) |
| 10 | Deployment (Fly + Render + Cloudflare + monitoring) | ⬜ | 2-3 | go live | [10-deployment/](phases/10-deployment/CLAUDE.md) |
| 11 | Reliability hardening (post-launch placeholder) | 🅿️ DEFERRED | TBD | scale beyond 50 clinics | [11-reliability-hardening/](phases/11-reliability-hardening/CLAUDE.md) |

**Total remaining (Phases 4.5-10, excluding Phase 5):** ~14-18 working days for a one-person execution. Phase 5 (WhatsApp) deferred to MVP2 per client decision 2026-06-03, saving ~4-5 days. Phase 6 reduced by ~1 day (WA jobs removed).

**Phase 5 is deferred to MVP2** per client decision 2026-06-03. Do NOT build WhatsApp functionality until after first paying clinic ships.

**Phase 11 is deferred** until one of three triggers fires (see Phase 11 doc). Do NOT pre-build it.

---

## What each phase produces

**Phase 4 — Backend Core**
A working FastAPI app at `localhost:8000`. JWT-protected routes scoped by `branch_id`. Existing Razorpay router wired in. Fresh Alembic migration that matches current schema. Standalone test app deleted.

**Phase 5 — WhatsApp (DEFERRED-MVP2)**
Doctor texts "list today" → gets formatted schedule. Patient texts a clinic number → state machine walks them through booking → confirmed token + WA confirmation. All without touching the voice agent. **Deferred to MVP2 per client decision 2026-06-03.**

**Phase 6 — Jobs + Calendar (MVP1 REDUCED)**
Confirmed bookings sync to Google Calendar. Token expiry job runs every 2 minutes to clean up stale tokens. WA-dependent jobs (EOD summary, follow-up tasks) deferred to MVP2.

**Phase 7 — Receptionist PWA**
React PWA. Receptionist opens it on their phone, sees today's queue grouped by doctor, taps to mark attended/no-show. Works offline (last queue cached, mutations queue and replay).

**Phase 8 — Owner + Admin dashboards**
Clinic owner sees last 30 days analytics for their branches. Vinay's admin view shows every org, plan, billing cycle, revenue.

**Phase 9 — Subscriptions + Onboarding**
Plan signup creates a Razorpay subscription (not just a one-time order). Owner onboarding wizard: pick plan → pay → Vobiz DID provisioned → first doctor + working hours → call forwarding instructions emailed. 14-day trial without card. Trial expiry job pauses on day 14.

**Phase 10 — Deployment**
Voice agent live on Fly Mumbai. Backend on Render Singapore. Landing + receptionist app on Cloudflare Pages. UptimeRobot monitoring. End-to-end test: real phone calls real DID, books real token, Google Calendar event created, real receptionist marks attended. No Meta WhatsApp infra needed for MVP1.

---

## How to start a phase

```bash
cd docs/phases/04-backend-core
# read CLAUDE.md
# work through the task list top-to-bottom
# commit after each task with the suggested message
# when the acceptance checklist is fully checked, update STATUS.md
```

---

## When a phase changes

If a phase doc gets significantly out of date during execution, update the phase's CLAUDE.md in-place AND update `STATUS.md`. Don't fork or version-bump — there's one truth per phase.
