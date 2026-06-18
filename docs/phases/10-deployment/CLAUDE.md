# Phase 10 — Deployment ⬜ TODO

**Goal:** Vachanam is live. A real patient calls a real DID, the AI answers in Telugu, books a real token, creates a Google Calendar event. A real receptionist marks them attended.

**Effort:** 2-3 days. **Prerequisites:** Phases 4-9 ✅ (except Phase 5 WhatsApp, deferred to MVP2). All production accounts active (Razorpay live KYC, Vobiz partner agreement signed, Google Cloud Calendar API). Meta WhatsApp Business account NOT required for MVP1.

---

## What gets deployed where

| Component | Host | Region | Reason |
|---|---|---|---|
| Voice agent | Fly.io Machines | `bom` (Mumbai) | Only India PaaS, lowest STT/TTS latency |
| Backend API | Render Web Service | Singapore | Most reliable India-adjacent Render region |
| Receptionist + Owner + Admin PWA | Cloudflare Pages | Global edge | Free, fast in India, 99.99% |
| Postgres | Neon | Singapore | Serverless, pooler built-in |
| Redis | Upstash | Mumbai region | Atomic INCR for token counters |
| LiveKit server | Fly.io (separate app) | `bom` | Co-located with agent |
| Monitoring | UptimeRobot | — | Free, 2-min checks, SMS alerts |
| Logs | Render dashboard + Fly logs | — | Structlog JSON aggregated locally; no Datadog yet (cost) |

---

## Deploy steps

### 1. Voice agent → Fly.io
```bash
flyctl launch --config infra/fly.agent.toml --no-deploy
flyctl secrets set SARVAM_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... \
                   LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... \
                   VOBIZ_SIP_DOMAIN=... VOBIZ_SIP_USERNAME=... VOBIZ_SIP_PASSWORD=... \
                   VOBIZ_DID_NUMBER=... VOBIZ_PARTNER_AUTH_ID=... VOBIZ_PARTNER_AUTH_TOKEN=... \
                   DATABASE_URL=... REDIS_URL=...
# META_ACCESS_TOKEN and META_PHONE_NUMBER_ID — NOT needed for MVP1 (WhatsApp deferred to MVP2)
flyctl deploy
```

### 2. Backend → Render
- Connect GitHub repo to Render
- Auto-detects `render.yaml` (repo root)
- Add `google-service-account.json` as a Secret File mounted at `/etc/secrets/`
- Fill all 25+ env vars in Render dashboard (use the `sync: false` keys from render.yaml as a checklist)

### 3. Frontend → Cloudflare Pages
```bash
cd frontend
npm run build
# Cloudflare Pages: connect repo, build cmd "npm run build", output "dist"
# add env vars: VITE_GOOGLE_OAUTH_CLIENT_ID, VITE_API_URL=https://vachanam-backend.onrender.com
```

### 4. DNS + SSL
- `api.vachanam.in` → Render
- `app.vachanam.in` → Cloudflare Pages
- `agent.vachanam.in` (optional) → Fly app for health checks
- Cloudflare handles SSL on its end; Render auto-issues via Let's Encrypt

### 5. Webhooks pointed to production
- Razorpay webhook → `https://api.vachanam.in/webhook/razorpay`
- LiveKit dispatch rule → agent.vachanam.in (or Fly internal address)
- ~~Meta WhatsApp webhook → `https://api.vachanam.in/webhook/whatsapp`~~ — MVP2 (after Phase 5 WhatsApp ships)

### 6. Run the migration in prod
```bash
DATABASE_URL=<neon-url> alembic upgrade head
```
Seed yourself as the first admin user via psql.

### 7. UptimeRobot
- Add monitors: `https://api.vachanam.in/health` (2-min, SMS to ADMIN_PHONE on down)
- Add monitor for agent Fly app health endpoint
- Add monitor for Cloudflare Pages

---

## Production checklist (acceptance criteria)

```
[ ] flyctl status — agent VM running, min_machines=1
[ ] curl https://api.vachanam.in/health → 200
[ ] curl https://app.vachanam.in/ → loads receptionist app shell
[ ] Real call from your phone → DID → agent answers in Telugu → "Token #1 confirmed" heard back
[ ] Google Calendar event created for the booking (visible in doctor's calendar)
[ ] Open app.vachanam.in on phone → login → see Token #1 in queue → tap Attended → server updates
[ ] Razorpay live mode: complete a real ₹1 subscription with own card, see BillingCycle row
[ ] UptimeRobot dashboard: all 3 monitors green
[ ] Structlog JSON visible in Render + Fly log streams
[ ] No secrets in git (run `git log --all -p | grep -iE "rzp_live|API_SECRET|ACCESS_TOKEN" | head` — must return nothing)
```

---

## Production runbook (link from CLAUDE.md after deploy)

| Symptom | First check | Mitigation |
|---|---|---|
| Patient says "AI didn't answer my call" | Fly agent VM status, LiveKit logs for room creation | If Fly down → flyctl machine restart; if LiveKit down → switch to Singapore standby |
| EOD summary not arriving | MVP2 feature (requires Phase 5 WhatsApp). Not expected in MVP1. | N/A for MVP1 |
| Token assignment failing | Upstash Redis status, check for INCR errors in agent logs | Failover: Upstash has 99.99% — if down, route to a fallback Redis or graceful "call back" message |
| Payment webhook missed | Razorpay dashboard → Webhooks → Delivery attempts | Re-trigger delivery from dashboard |

---

## What this phase does NOT do

- ❌ No multi-region failover (single Mumbai region for MVP)
- ❌ No managed log aggregation (Render + Fly built-in only)
- ❌ No paging on-call rotation (Vinay's phone is the on-call)
- ❌ No load testing — defer until 10 concurrent clinics
- ❌ No backups beyond Neon's default daily — fine for MVP

---

## After Phase 10

Vachanam is live. Focus shifts to:
- Sales (first 5 paying clinics across India)
- Watch metrics: call answer rate, booking conversion %, churn
- Iterate on weak points found in real usage
- Post-MVP backlog: full TYPE_1/TYPE_2 emergency classification, CSV exports, multi-language UI for receptionist, scheduled migration to Postgres 17, separate read replica, Datadog when budget allows.
