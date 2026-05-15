# PHASE_5_PRODUCTION.md — Production Deployment + Always-Up Strategy
## This is the final phase. Nothing ships to a real client without every item checked.
## A bug here affects real patients with real health issues. Be precise.

---

## WHY THIS PHASE IS DIFFERENT FROM EVERYTHING BEFORE IT

Development is forgiving. Production is not.

In development: a crash means you fix it and retry.
In production: a crash means:
- A patient with chest pain cannot book an urgent appointment
- A clinic misses revenue (₹400/consultation × every missed call)
- A clinic owner calls you, angry
- You lose a client

Every item in this phase exists to prevent a specific failure mode.
Every checklist item has been learned from real production incidents
at similar SaaS products. None of it is optional.

**Time estimate:** 3 days
**Monthly burn:** ₹3,048 until first client
**Your uptime target:** 99.4% overall (all mitigations active)

---

## DEPLOY ORDER — NEVER CHANGE THIS SEQUENCE

```
1. Neon Postgres   → database must be ready before backend
2. Render backend  → API must be running before agent
3. Fly.io agent    → agent needs backend and DB running
4. Cloudflare PWA  → frontend needs API URL
5. UptimeRobot     → monitoring must start LAST (after all services up)
6. Singapore VM    → failover after primary is confirmed working
7. Manual test     → full end-to-end call before any client is onboarded
```

---

## STEP 1: NEON POSTGRES — PRODUCTION DATABASE

```bash
# 1. Create Neon project at neon.tech
#    Project name: vachanam-production
#    Region: US East (aws-us-east-2) — closest to Render Oregon

# 2. Copy connection string from Neon dashboard
#    Format: postgresql+asyncpg://user:password@host/dbname?sslmode=require

# 3. Run migrations against production database
export DATABASE_URL="postgresql+asyncpg://neon_prod_connection_string"
alembic upgrade head

# 4. Verify all 10 tables exist
psql "postgresql://neon_prod_connection_string" -c "\dt"
# Expected: 10 tables listed

# 5. IMPORTANT: Neon free tier pauses after 5 minutes of inactivity
# Upgrade to Launch plan ($5/month) BEFORE going to production
# Free tier pauses = 5-10 second cold start = first API call fails
```

---

## STEP 2: RENDER BACKEND — PRODUCTION API

### render.yaml (commit to repo root)
```yaml
services:
  - type: web
    name: vachanam-backend
    runtime: python
    region: oregon
    plan: starter
    buildCommand: pip install -r backend/requirements.txt
    startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 2
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: APP_ENV
        value: production
      - key: LOG_LEVEL
        value: info
      - key: BASE_URL
        value: https://vachanam-backend.onrender.com
      - key: FRONTEND_URL
        value: https://vachanam.pages.dev
      # Set these manually in Render dashboard (never in render.yaml):
      # DATABASE_URL, REDIS_URL, SARVAM_API_KEY, OPENAI_API_KEY,
      # GEMINI_API_KEY, META_ACCESS_TOKEN, META_PHONE_NUMBER_ID,
      # META_APP_SECRET, META_WEBHOOK_VERIFY_TOKEN, VOBIZ_PARTNER_AUTH_ID,
      # VOBIZ_PARTNER_AUTH_TOKEN, JWT_SECRET, RAZORPAY_KEY_ID,
      # RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, ADMIN_PHONE,
      # GOOGLE_CALENDAR_SERVICE_EMAIL
```

### Deploy
```bash
# Commit render.yaml
git add render.yaml
git commit -m "feat: add render.yaml for production deployment"
git push origin main

# In Render dashboard:
# 1. New → Web Service
# 2. Connect GitHub repository
# 3. Select render.yaml (auto-detected)
# 4. Set all secrets in Environment tab
# 5. Deploy

# Verify
curl https://vachanam-backend.onrender.com/health
# → {"status":"ok","version":"1.0.0","env":"production"}

# Check logs (Render dashboard → Logs tab)
# Must show: "startup", "database_initialized", "scheduler_started"
# Must NOT show: any ERROR level messages
```

---

## STEP 3: FLY.IO AGENT — PRODUCTION VOICE AGENT

### infra/fly.agent.toml
```toml
app = "vachanam-agent"
primary_region = "bom"

[build]
  dockerfile = "infra/Dockerfile.agent"

[env]
  APP_ENV = "production"
  LOG_LEVEL = "info"
  PYTHONPATH = "/app"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false
  min_machines_running = 1

  [http_service.concurrency]
    type = "requests"
    hard_limit = 50
    soft_limit = 20

[[vm]]
  cpu_kind = "shared"
  cpus = 2
  memory_mb = 1024

[restart]
  policy = "always"
  max_retries = 10

[[checks]]
  name = "health"
  port = 8080
  type = "http"
  interval = "30s"
  timeout = "5s"
  grace_period = "20s"
  path = "/health"
```

### infra/Dockerfile.agent
```dockerfile
FROM python:3.11-slim

# Install ffmpeg for audio processing
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY agent/requirements.txt ./agent/
RUN pip install --no-cache-dir -r agent/requirements.txt

COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY agent/ ./agent/
COPY backend/ ./backend/

# Copy Google service account (set as Fly.io secret in production)
# Handled via environment variable in production

ENV PYTHONPATH=/app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import httpx; r = httpx.get('http://localhost:8080/health', timeout=4); r.raise_for_status()" || exit 1

CMD ["python", "-m", "agent.agent", "start", "--port", "8080"]
```

### Deploy
```bash
# Run full test suite first — mandatory
pytest tests/ -m "not slow" -q
# MUST show: "X passed" with 0 failures
# If ANY test fails: DO NOT DEPLOY. Fix the failing test first.

# Create Fly.io app
fly apps create vachanam-agent

# Set ALL secrets (do NOT put these in fly.toml or code)
fly secrets set \
  SARVAM_API_KEY="your_sarvam_key" \
  OPENAI_API_KEY="your_openai_key" \
  GEMINI_API_KEY="your_gemini_key" \
  GEMINI_API_KEY="your_gemini_key" \
  VOBIZ_API_KEY="your_vobiz_key" \
  VOBIZ_API_SECRET="your_vobiz_secret" \
  VOBIZ_WEBHOOK_SECRET="your_webhook_secret" \
  VOBIZ_PARTNER_AUTH_ID="your_partner_id" \
  VOBIZ_PARTNER_AUTH_TOKEN="your_partner_token" \
  LIVEKIT_URL="wss://vachanam-agent.fly.dev" \
  LIVEKIT_API_KEY="your_livekit_key" \
  LIVEKIT_API_SECRET="your_livekit_secret" \
  DATABASE_URL="postgresql+asyncpg://neon_prod_url" \
  REDIS_URL="rediss://upstash_prod_url" \
  JWT_SECRET="$(openssl rand -hex 32)" \
  ADMIN_PHONE="+91XXXXXXXXXX" \
  APP_ENV="production" \
  --app vachanam-agent

# Google service account — store as secret
fly secrets set \
  GOOGLE_CREDENTIALS_JSON="$(cat google-service-account.json)" \
  --app vachanam-agent
# In config.py: read from GOOGLE_CREDENTIALS_JSON env var and write to temp file

# Deploy
fly deploy --config infra/fly.agent.toml

# Monitor deployment
fly status --app vachanam-agent
# Wait for: Status = running

# Verify health
curl https://vachanam-agent.fly.dev/health
# → {"status":"ok"}

# Watch live logs for 5 minutes
fly logs --app vachanam-agent --tail
# Must NOT show: ERROR, CRITICAL, exception, traceback
# Must show: "startup" message
```

---

## STEP 4: CLOUDFLARE PAGES — FRONTEND

```bash
# Build test locally
cd frontend
npm run build
# Must complete without errors

# Deploy via Cloudflare dashboard:
# 1. Cloudflare Dashboard → Pages → Create Application
# 2. Connect to Git → Select GitHub repository
# 3. Build settings:
#    Build command: cd frontend && npm install && npm run build
#    Build output directory: frontend/dist
#    Root directory: / (not frontend — vite builds relative to root)
# 4. Environment variables:
#    VITE_API_URL = https://vachanam-backend.onrender.com
#    VITE_GOOGLE_CLIENT_ID = your_google_client_id.apps.googleusercontent.com
# 5. Save and Deploy

# Verify
curl -I https://vachanam.pages.dev
# → HTTP 200 or 304

# Custom domain setup (optional):
# Cloudflare → Pages → vachanam → Custom Domains
# Add: app.vachanam.in → Cloudflare proxied DNS
```

---

## STEP 5: UPTIME MONITORING — UPTIMEROBOT

Create account at uptimerobot.com (free, no credit card).

Create these 5 monitors:

```
Monitor 1: Voice Agent Health
  Type: HTTP(s)
  URL: https://vachanam-agent.fly.dev/health
  Check interval: 2 minutes
  Alert when: down for 2 minutes
  Alert contacts: your phone (SMS) + your WhatsApp

Monitor 2: Backend API Health
  Type: HTTP(s)
  URL: https://vachanam-backend.onrender.com/health
  Check interval: 2 minutes
  Alert when: down for 2 minutes
  Alert contacts: same

Monitor 3: Frontend
  Type: HTTP(s)
  URL: https://vachanam.pages.dev
  Check interval: 5 minutes
  Alert when: down for 5 minutes
  Alert contacts: same

Monitor 4: Sarvam API Status
  Type: HTTP(s)
  URL: https://status.sarvam.ai
  Check interval: 5 minutes
  Alert when: down for 5 minutes
  Alert contacts: same

Monitor 5: Upstash Redis Status
  Type: HTTP(s)
  URL: https://status.upstash.com
  Check interval: 5 minutes
  Alert when: down for 5 minutes
  Alert contacts: same
```

---

## STEP 6: SINGAPORE FAILOVER VM

```bash
# After Mumbai VM is confirmed working for 30 minutes:

# Add Singapore as secondary region in fly.agent.toml
# Edit [[vm]] section to add:
[[vm]]
  count = 1
  cpu_kind = "shared"
  cpus = 2
  memory_mb = 1024

# Scale to include Singapore
fly scale count 2 --regions bom=1,sin=1 --app vachanam-agent

# Verify both machines running
fly status --app vachanam-agent
# Should show 2 machines: bom (Mumbai) + sin (Singapore)

# Test failover:
fly machine list --app vachanam-agent
# Note the Mumbai machine ID

fly machine stop [mumbai_machine_id] --app vachanam-agent
# Wait 60 seconds

# Make a test call to the DID
# Call should connect (Singapore now handling)

fly machine start [mumbai_machine_id] --app vachanam-agent
# Mumbai comes back
```

**What happens automatically:**
- Fly.io load balancer detects Mumbai VM unhealthy (health check fails)
- Load balancer routes all new calls to Singapore VM
- Singapore VM is always running (`min_machines_running = 1` for both)
- When Mumbai recovers, load balancer routes to whichever is healthier
- No manual intervention needed for most outages

---

## STEP 7: LLM FALLBACK — VERIFY IN PRODUCTION

```bash
# Test that Gemini fallback works when OpenAI is unavailable.
# Method: temporarily use a wrong OpenAI API key in dev environment.

# In .env (local dev only):
OPENAI_API_KEY=sk-invalid-key-to-test-fallback

# Make a test call to local agent
# Expected: call still works (Gemini takes over)
# Logs show: "openai_failed_switching_to_gemini"

# Restore real key after test
OPENAI_API_KEY=sk-real-key

# Note: never test this on production — disrupts live calls
```

---

## STEP 8: TWILIO BACKUP SIP TRUNK

```bash
# Twilio is your insurance policy.
# If Vobiz goes down, you re-route all clinics to Twilio in < 5 minutes.

# Setup:
# 1. Create Twilio account (just Gmail, no documents)
# 2. Buy Indian DID: +1 = $1/month (Twilio India numbers are US numbers)
#    OR: buy Indian local number from Twilio India portal
# 3. Configure SIP trunk in Twilio to point to your LiveKit agent

# Configure LiveKit to accept Twilio SIP:
# In LiveKit server config, add Twilio as allowed SIP source

# When Vobiz fails (procedure takes 5 minutes):
# 1. UptimeRobot SMS alert fires
# 2. Log into Vobiz Partner portal — confirm outage
# 3. Update LiveKit SIP configuration to use Twilio trunk
# 4. Clinics re-dial USSD with Twilio DID: **21*+1-XXXXXXXXXX#
#    (send them this code via WhatsApp immediately)
# 5. Voice calls routed via Twilio

# This procedure should be documented and practiced before first client.
```

---

## PRE-LAUNCH CHECKLIST — 40 ITEMS

**Every single item must be checked. No exceptions.**

```
SECURITY
□ git log --oneline | head -20 → no .env or .json secret files
□ grep -r "sk-" backend/ → 0 matches (no hardcoded OpenAI keys)
□ grep -r "api_key\s*=" agent/ → 0 hardcoded values
□ fly secrets list → all 15+ secrets listed (none in fly.toml)
□ Render env vars → all secrets set (none in render.yaml values)

TESTS
□ pytest tests/unit/ -v → 0 failures
□ pytest tests/edge_cases/test_concurrent_tokens.py -v → 0 failures
□ pytest tests/edge_cases/test_data_isolation.py -v → 0 failures
□ ruff check agent/ backend/ → 0 errors

INFRASTRUCTURE
□ curl https://vachanam-agent.fly.dev/health → {"status":"ok"}
□ curl https://vachanam-backend.onrender.com/health → {"status":"ok"}
□ curl -I https://vachanam.pages.dev → HTTP 200
□ alembic upgrade head on production → "No upgrades to apply" (all current)
□ psql production_neon_url -c "\dt" → 10 tables listed
□ redis-cli -u $REDIS_URL ping → PONG

UPTIME MONITORING
□ All 5 UptimeRobot monitors show green
□ UptimeRobot SMS test → SMS received on your phone < 3 minutes
□ fly logs --app vachanam-agent → 0 ERROR or CRITICAL entries for 10 minutes

FULL END-TO-END VOICE CALL (production)
□ Using a real phone, call the Vobiz DID
□ AI answers within 2 rings (< 6 seconds from first ring)
□ AI greets in Telugu
□ Say a health issue (e.g. "fever undi, doctor kavali")
□ AI routes to correct doctor based on clinic config
□ Say patient name when asked
□ AI assigns token number (hear it spoken)
□ AI confirms booking (hear the token number again)
□ Call ends
□ Patient WhatsApp received within 60 seconds
□ Doctor WhatsApp received within 90 seconds
□ Token visible in production Neon DB:
  psql prod_url -c "SELECT * FROM tokens ORDER BY created_at DESC LIMIT 1;"
□ Calendar event visible in Google Calendar

EMERGENCY DETECTION (production)
□ Call the DID
□ Say "collapse aipōyāḍu" (patient collapsed)
□ AI does NOT continue booking flow
□ AI says "Ippude connect chestunna. Location cheppandi."
□ Call log: call_logs.was_emergency = True
□ Call log: call_logs.emergency_type = "type_1"
□ NOT: "Token 8 available for Dr. Y" (wrong — emergency not detected)

TOKEN RELEASE (production)
□ Start a booking call, get to token assignment
□ Hang up before saying "confirm" or "yes"
□ Check Redis: key should be decremented
□ Check DB: no token record for this partial booking

WHATSAPP FLOWS (production)
□ Send "list today" from your phone to the clinic's Meta WhatsApp number
  → Format-rich schedule received within 30 seconds
□ Send "off tomorrow" → patients (if any) notified, you confirmed

FAILOVER (production)
□ Singapore standby VM confirmed running:
  fly status --app vachanam-agent → 2 machines shown
□ Mumbai failover test:
  Stop Mumbai VM → wait 90 seconds → make test call → agent answers
  Start Mumbai VM back
□ Your phone received SMS from UptimeRobot during Mumbai stop

LLM FALLBACK (staging, not production)
□ Gemini fallback tested with invalid OpenAI key → calls still work

MONITORING LOGS
□ After 10-minute monitoring period, fly logs shows:
  ✓ "call_started" entries
  ✓ "booking_confirmed" entries
  ✓ NO "ERROR" level entries
  ✓ NO Python tracebacks

ROLLBACK READINESS
□ Previous Fly.io release noted:
  fly releases --app vachanam-agent → write down previous image tag
□ Rollback command tested (staging):
  fly deploy --image [previous_tag] → app still starts
□ Render rollback: know where the "Deploy" button is
  (Render Dashboard → Service → Deploys → select previous → click Deploy)
```

---

## INCIDENT RESPONSE RUNBOOK

### When you receive a UptimeRobot SMS

**Step 1: Identify the failing service**
```bash
# Check which services are down
curl https://vachanam-agent.fly.dev/health
curl https://vachanam-backend.onrender.com/health
curl https://vachanam.pages.dev

# Check Fly.io status
fly status --app vachanam-agent
fly logs --app vachanam-agent --tail
```

**Step 2: Classify the incident**
```
Agent health fails:
  → Check fly status → any machines crashed?
  → fly machine restart [crashed_machine_id]
  → If Mumbai region outage: Singapore auto-handles, wait for Mumbai

Backend health fails:
  → Render dashboard → check if deploy failed
  → Manual restart: Render Dashboard → Service → Restart

Sarvam status fails:
  → Check status.sarvam.ai directly
  → If outage confirmed: send WhatsApp to all clinics
    Template: "AI voice temporarily down. Receptionist will answer calls manually.
    We'll notify when restored. Sorry for inconvenience."

Vobiz status fails:
  → Test by calling DID from another phone
  → If calls not connecting: activate Twilio backup SIP
  → Send clinics new USSD code for Twilio number
```

**Step 3: Communicate**
```bash
# Send status update to all active clinics via WhatsApp
# Use the admin_broadcast function (add to backend in Phase 2 extras):
curl -X POST https://vachanam-backend.onrender.com/admin/broadcast \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -d '{"message": "Brief outage resolved. Service fully restored."}'
```

**Step 4: Post-incident**
```
After every incident (even minor):
□ Check fly logs for root cause
□ Note duration and impact in a text file
□ If > 30 minutes: send personal apology to affected clinics
□ If Fly.io fault: consider upgrading to dedicated VM ($38/month)
```

---

## ONGOING OPERATIONS CHECKLIST

### Daily (2 minutes)
```
□ UptimeRobot dashboard → all green
□ fly logs --app vachanam-agent → no ERROR entries overnight
□ Render logs → no ERROR entries overnight
```

### Weekly (15 minutes)
```
□ Review total call count (Fly.io metrics or structlog aggregation)
□ Review Vobiz wallet balances (check Partner dashboard)
□ Check Neon database size (free tier limit: 512MB on Launch plan)
□ Review failed WhatsApp deliveries in whatsapp_logs table
```

### Monthly (30 minutes)
```
□ Test Singapore failover manually
□ Test LLM fallback manually (staging environment)
□ Review Sarvam API credits remaining
□ Update PHASE files if any tool has changed pricing/APIs
□ Review and rotate JWT_SECRET if security concern
```

---

## UPTIME SUMMARY

| Service | Realistic Uptime | Worst Case Downtime/Year | Mitigation |
|---|---|---|---|
| Sarvam STT/TTS | 99.99% | 53 minutes | Graceful callback message |
| Gemini 2.5 Flash | 99.9% | 8.7 hours | Auto-switch to GPT-4o mini (fallback) |
| Vobiz telephony | 99.9% | 8.7 hours | Twilio backup SIP (5 min switchover) |
| Fly.io bom | 99.0–99.5% | 1.8–3.6 days | Singapore standby (auto-failover 60s) |
| Render backend | 99.9% | 8.7 hours | Auto-restart (30s recovery) |
| Neon Postgres | 99.9% | 8.7 hours | Daily automatic backups |
| Upstash Redis | 99.99% | 53 minutes | DB fallback (SELECT FOR UPDATE) |
| Meta WhatsApp | 99.9% | 8.7 hours | Logged + retry queue |
| Cloudflare CDN | 99.99% | 53 minutes | Global CDN (no single point) |
| **Overall** | **~99.4%** | **~52 hours/year** | All mitigations active |

---

## PHASE 5 EXIT CRITERIA

```
AUTOMATED TESTS
□ pytest tests/ -m "not slow" -q → 0 failures

INFRASTRUCTURE
□ All 5 UptimeRobot monitors green for 30 consecutive minutes
□ fly status shows Mumbai + Singapore both running
□ Neon DB on Launch plan (not free tier)
□ Render backend on Starter plan (not free — free spins down)

END-TO-END
□ Production call: patient calls → AI answers → books → WhatsApp received
□ Emergency: "collapse aipōyāḍu" → correct handling → logged
□ Token release: call drop before confirm → Redis key decremented
□ Doctor command: "list today" → formatted schedule received
□ PWA: install on Android → works offline

FAILOVER
□ Singapore failover: manually tested and confirmed working
□ Twilio backup: SIP trunk configured, tested in staging
□ GPT-4o → Gemini fallback: tested in staging, logs confirm switch
□ Rollback procedure: tested once and documented

SECURITY
□ No secrets in code or config files
□ All API keys in Fly.io secrets and Render environment
□ HTTPS everywhere (no HTTP)
□ Webhook signatures verified (Meta + Razorpay)
□ Branch isolation verified: Clinic A cannot see Clinic B's data

WHEN ALL 40 PRE-LAUNCH ITEMS AND ALL EXIT CRITERIA ARE CHECKED:
You are ready to onboard your first paying client.

The first client gets full white-glove onboarding.
You call them. You walk them through the USSD code.
You make a test call with them present.
You confirm they receive WhatsApp confirmation.

After the first 3 clients are running smoothly:
Onboarding becomes fully self-serve.
The only thing you do is check the "New client!" WhatsApp.
```

---

## MONTHLY COST BREAKDOWN AT SCALE

```
INFRASTRUCTURE (fixed, shared across all clients)
  Fly.io bom + sin VMs:      ₹1,260/month (2 VMs)
  Render backend:            ₹588/month
  Neon Postgres:             ₹420/month
  Upstash Redis:             ₹0 (free tier through ~30 clients)
  Cloudflare Pages:          ₹0
  UptimeRobot:               ₹0
  Twilio DID (backup):       ₹84/month
  ────────────────────────────────────────────────
  Total fixed infra:         ₹2,352/month

PER-CLINIC VARIABLE COSTS (Clinic plan, 20 calls/day)
  Sarvam STT:                ₹520
  Sarvam TTS:                ₹312
  Vobiz streaming:           ₹676
  Vobiz DID:                 ₹1,000
  Gemini 2.5 Flash:          ₹10
  Meta Cloud API:            ₹78
  ────────────────────────────────────────────────
  Total per clinic:          ₹2,596/month

REVENUE AND MARGIN (Clinic plan ₹7,999)
  Revenue:                   ₹7,999
  Variable cost:             ₹2,596
  Contribution margin:       ₹5,403 (68%)
  Fixed infra share (÷10):  ₹235
  Net margin per client:     ₹5,168 (65%)

AT 10 CLINIC CLIENTS
  MRR:                       ₹79,990
  Variable costs:            ₹25,960
  Fixed infra:               ₹2,352
  Net profit:                ₹31,698/month (53%)
  Annual:                    ₹3,80,376

AT 20 CLINIC CLIENTS
  MRR:                       ₹1,19,980
  Variable costs:            ₹51,880
  Fixed infra:               ₹2,352
  Net profit:                ₹65,748/month (55%)
  Annual:                    ₹7,88,976

With Sarvam startup credits (STT+TTS = ₹0):
  At 20 clients net profit:  ₹82,148/month (68%)
```
