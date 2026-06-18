# Vachanam — Deploy Runbook (go-live)

Topology: **Render** = backend API · **Fly.io (Mumbai)** = voice agent · **Cloudflare Pages** = frontend · **Neon** = DB · **Upstash** = Redis. (Backend on Render is fine — latency-critical path is the agent, which is on Fly Mumbai and talks directly to Neon/LiveKit/providers.)

Already done (2026-06-17): Neon + schema/migrations (head q14) · Upstash · FIELD_ENCRYPTION_KEY · JWT · Resend · LiveKit/Vobiz/Google creds verified · super_admin `vachanamai@gmail.com` seeded.

---

## What a LIVE CALL actually needs (do these first)

1. **Agent deployed (Fly)** — answers the call, runs the pipeline.
2. **Vobiz DID → LiveKit SIP inbound trunk** — the call reaches LiveKit.
3. **LiveKit dispatch rule → the agent** — LiveKit hands the call to the worker.
4. **One clinic in the DB** with that DID on its branch (RULE 5: branch resolved by dialed DID). With exactly one branch, the agent's DID fallback also covers it.

Everything else (dashboard, payments) is not on the call path.

---

## 1. Backend → Render

1. Render → New → Blueprint → point at the repo (auto-detects `render.yaml` at the repo root).
2. Set every `sync: false` env var in the Render dashboard (secrets + `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `SMALLEST_API_KEY`, `RESEND_API_KEY`, `BASE_URL=https://api.vachanam.in`, `FRONTEND_URL=https://vachanam.in`, `ADMIN_PHONE`). Razorpay vars can wait (trial).
3. Upload `google-service-account.json` as a **Secret File** at `/etc/secrets/google-service-account.json`.
4. Deploy. `preDeployCommand` runs `alembic upgrade head` (no-op now; applies future migrations). Health check `/health`.
5. Push-to-deploy is automatic thereafter.

## 2. Agent → Fly (Mumbai)

```
fly launch --no-deploy --config infra/fly.agent.toml   # first time
fly secrets set \
  SARVAM_API_KEY=... SMALLEST_API_KEY=... GEMINI_API_KEY=... OPENAI_API_KEY=... \
  LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... \
  VOBIZ_SIP_DOMAIN=... VOBIZ_SIP_USERNAME=... VOBIZ_SIP_PASSWORD=... VOBIZ_DID_NUMBER=... \
  VOBIZ_PARTNER_AUTH_ID=... VOBIZ_PARTNER_AUTH_TOKEN=... \
  DATABASE_URL=... REDIS_URL=... JWT_SECRET=... FIELD_ENCRYPTION_KEY=... \
  GOOGLE_OAUTH_CLIENT_ID=... GOOGLE_OAUTH_CLIENT_SECRET=... GOOGLE_CALENDAR_SERVICE_EMAIL=... \
  TRANSCRIPT_CAPTURE_ENABLED=true ADMIN_PHONE=...
fly deploy --config infra/fly.agent.toml
```
- Google SA: base64 into a secret, or bake into the image; `GOOGLE_APPLICATION_CREDENTIALS` = its path.
- Keep exactly 1 machine always-on (voice can't cold-start).
- `DATABASE_URL` must be `postgresql+asyncpg://...` with **no** `?sslmode=require`.

## 3. Telephony routing (Vobiz → LiveKit → agent)

- LiveKit: create an **inbound SIP trunk** + a **dispatch rule** that routes inbound SIP to the agent (`agent_name` in `fly.agent.toml`).
- Vobiz: point the DID's inbound destination at the LiveKit SIP URI.
- Confirm the dispatch rule passes the `sip.trunkPhoneNumber` attribute (RULE 5 tenant routing).

## 4. Frontend → Cloudflare Pages

- Connect repo. Root `frontend`, build `npm run build`, output `frontend/dist`.
- Env `VITE_API_URL=https://api.vachanam.in`.

## 5. DNS (Cloudflare)

- `vachanam.in` → Pages · `api.vachanam.in` → Render · Resend domain records (done).

## 6. First clinic + live-call test

1. Onboard a clinic via `/register` (creates org_admin + branch, 14-day trial) — or the owner self-registers.
2. In Settings: set the branch's **DID number**, language, doctor(s). For a sub-account clinic, paste Vobiz auth_id/token + SIP (stored encrypted).
3. Super_admin: log in at `/admin` with `vachanamai@gmail.com` (Google) → Operations + Monitoring.
4. **Call the DID** → agent answers, books, drops a `call_quality` row → appears on the owner Dashboard + `/admin/monitoring`.

## 7. Monitoring

- UptimeRobot → `https://api.vachanam.in/health`.
- Agent logs: `fly logs`. Per-turn latency lines: `lat_eou/llm/tts/stt`.

---

## Post-go-live (not blocking)
- Razorpay: keys + 3 plan IDs + webhook `https://api.vachanam.in/api/razorpay-webhook` (during the 14-day trial).
- Add more super_admins via the admin console (or `scripts/create_super_admin.py`).
