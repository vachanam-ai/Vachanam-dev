# Vachanam — Security & Compliance Hardening (Design Spec)

**Date:** 2026-05-22
**Author:** Vinay Rongala
**Status:** Approved (pending implementation plan)
**Posture target:** MVP-launch — best-effort security for first 5-20 paying clinics
**Slots into:** Phase 4.5 — between Phase 4 (Backend Core) and Phase 5 (WhatsApp)

---

## 1. Why this spec exists (plain English)

Vachanam handles patient names, phone numbers, complaint summaries, doctor schedules, and money. If any of that leaks, three bad things happen:

1. **Patients lose trust** — a clinic that broadcasts their phone number to spammers won't get a second appointment.
2. **The clinic owner gets sued** — under the Digital Personal Data Protection (DPDP) Act of 2023, the clinic is the "Data Fiduciary" and Vachanam is the "Data Processor." Both share liability. Fines can reach ₹250 crore per incident.
3. **Vachanam loses business** — one breach kills word-of-mouth growth permanently in a small market like Hyderabad clinics.

We are pre-launch with zero real patient data. This is the cheapest possible moment to design security in. Retrofitting it after we have 50 clinics and 100,000 patient records is 10× more expensive and 100× riskier.

This spec covers everything we need to ship securely:
- Who could attack us and how (Section 3 — threat model)
- The defenses we put in place (Sections 4-9)
- What to do when something goes wrong (Section 10 — breach runbook)
- How we prove it works (Section 11 — tests)
- When this gets built (Section 12 — implementation order)

The whole thing assumes a Defense-in-Depth model: many small defenses layered, so that any single one failing does not breach data.

---

## 2. What "MVP-launch posture" means

Three security postures were considered:

| Posture | When you use it | What's required |
|---|---|---|
| **MVP-launch** ← we picked this | 5-20 friendly customers, pre-product-market-fit | Privacy policy, OWASP basics, rate limit, session timeout, audit log for sensitive actions |
| Scale-ready | 50+ customers, real attackers | Above + formal DPO contact + WAF + quarterly self-audit + optional 2FA |
| Enterprise-grade | Healthcare chains, audited buyers | Above + SOC2 track + field-level PII encryption + mandatory 2FA + third-party penetration test |

We do not need scale-ready or enterprise grade today. We DO need a clear path to upgrade — every decision in this spec is forward-compatible with both higher postures. Upgrading later means adding things, not replacing things.

---

## 3. Threat model — who could attack us

| Attacker | What they want | How they try | Our defense |
|---|---|---|---|
| Random internet scanner | Any working URL to exploit | Mass HTTP scans, default-credential probing, known-CVE exploits | Cloudflare edge + non-default deployment + Dependabot keeps deps patched |
| Bot trying to scrape | Patient phone numbers for spam lists | Hit `/queue/*` repeatedly | JWT auth required + per-user rate limit + audit log catches anomaly |
| Credential-stuffer | Take over a clinic owner's account | Try leaked Google passwords against `/auth/google` | Google handles password security; we rate-limit `/auth/google` to 5/min/IP |
| Phone thief | Use a stolen receptionist phone | Open the PWA, do damage before discovery | 30-min idle timeout + 8h JWT max + audit log shows exactly what they touched |
| Malicious other clinic | See competitor's patient list, sabotage bookings | Find an API endpoint, send their JWT with a different `branch_id` in the URL | Every DB query filters by `branch_id` (the "WHERE clause is final tripwire" rule); `branch_guard` middleware also checks JWT against URL |
| Insider (rogue receptionist) | Exfiltrate patient list before quitting | Bulk-download via `/queue/*` | Audit log + per-user rate limit + post-departure access revocation in HR runbook |
| Payment fraudster | Forge a payment success | Send fake Razorpay webhook | HMAC-SHA256 signature verification with `RAZORPAY_WEBHOOK_SECRET`; mismatch → 400 + audit log |
| DDoS attacker | Take Vachanam offline | Volumetric traffic to backend | Cloudflare DDoS protection at edge (free tier handles up to ~100 Gbps) |
| State-level actor (low probability) | Surveillance of specific clinic | Direct database access via vendor compromise | Out of MVP scope. Field-level encryption (Scale-ready posture) is the upgrade path. |

**Threats NOT in scope for MVP:**
- Physical theft of Render or Neon data center (their problem, covered in their SOC2)
- Quantum-computer-broken TLS (decades away)
- Targeted social engineering of Vinay specifically (mitigated by 2FA on Google account — owner's responsibility)

---

## 4. Layered architecture (the big picture)

When a request enters the system, it passes through four layers. Each layer must independently approve the request. If any layer rejects, the request dies there.

```
                  ┌─────────────────────────────────────┐
                  │   PUBLIC INTERNET                   │
                  └──────────────┬──────────────────────┘
                                 ↓
                  ┌─────────────────────────────────────┐
   LAYER 1: EDGE  │   Cloudflare (free tier)            │
   (CDN/WAF)      │   • DDoS protection                 │
                  │   • Managed WAF rules (OWASP CRS)   │
                  │   • TLS 1.2+ termination            │
                  │   • Bot Fight Mode: challenge bots  │
                  │   • Country block (optional)        │
                  └──────────────┬──────────────────────┘
                                 ↓ HTTPS to api.vachanam.in (Render)
                  ┌─────────────────────────────────────┐
   LAYER 2: APP   │   FastAPI middleware stack:         │
   (per request)  │   1. SecurityHeadersMiddleware      │
                  │      (CSP, HSTS, X-Frame, etc.)     │
                  │   2. CORSMiddleware (strict)        │
                  │   3. RateLimitMiddleware (slowapi)  │
                  │   4. AuthMiddleware (JWT decode)    │
                  │   5. AuditMiddleware (log writes)   │
                  └──────────────┬──────────────────────┘
                                 ↓
                  ┌─────────────────────────────────────┐
   LAYER 3: ROUTE │   Per-endpoint:                     │
   (handler)      │   • Pydantic strict input validate  │
                  │   • branch_guard (multi-tenant)     │
                  │   • require_admin (admin routes)    │
                  │   • @audit decorator                │
                  └──────────────┬──────────────────────┘
                                 ↓
                  ┌─────────────────────────────────────┐
   LAYER 4: DATA  │   • SQLAlchemy ORM (no raw SQL)     │
   (database)     │   • branch_id WHERE on every query  │
                  │   • Neon encryption at rest         │
                  │   • Append-only audit_log table     │
                  └─────────────────────────────────────┘
```

**Why four layers?** Each layer assumes the others might fail. Examples:

- Cloudflare misconfigured? The app rate-limiter still throttles abuse.
- JWT stolen? The audit log records every action; per-user rate limit caps damage.
- `branch_guard` middleware has a bug? The `WHERE branch_id = ?` in the SQL is the final defense.

This is "defense in depth." A breach requires multiple independent failures, not one.

---

## 5. Authentication & session management (plain English)

### 5.1 Who logs in, who doesn't

| Role | How they identify themselves | Notes |
|---|---|---|
| Clinic owner | Google account | Google handles password + 2FA |
| Receptionist | Google account (added by owner with their email) | If receptionist has no Google account, owner sets one up free at gmail.com |
| Vachanam admin (Vinay) | Google account + `is_admin=true` flag in DB | Manually flipped via psql once after first login |
| Doctor | Doesn't log in. Identified by `Doctor.whatsapp_number` matching the sender of WhatsApp messages | Meta webhook signature is the auth |
| Patient | Doesn't log in. Identified by phone number on voice call or `Patient.phone` matching WhatsApp sender | Meta webhook signature is the auth; voice agent receives caller ID via SIP |

**Why Google only?** Three reasons:

1. **We don't store passwords.** Password storage means hashing, password-reset flows, breach response when passwords leak — all of which we delegate to Google for free.
2. **Google has world-class 2FA.** Any owner serious about security can enable it on their Google account. Adding our own 2FA layer would be redundant for them and friction for everyone else.
3. **Receptionists don't get account-takeover via SMS.** SMS-OTP-based logins are vulnerable to SIM swap attacks, which are common in India. Forcing Google instead avoids this entire class of attack.

### 5.2 The login flow, step by step

1. Frontend shows a "Sign in with Google" button. User clicks. Google authenticates them.
2. Google returns an "ID token" (a signed JWT containing their email, name, and a permanent `sub` identifier).
3. Frontend sends that ID token to our backend at `POST /auth/google`.
4. Backend verifies the ID token with Google's public keys (via `google.oauth2.id_token.verify_oauth2_token`). This proves the user actually authenticated with Google — nobody can forge this.
5. Backend looks up our `users` table: first by `google_sub`, then by `email`. If no row exists, return 403 — "Not registered. Contact your clinic admin."
6. If user exists, backend issues a **Vachanam JWT** (different from Google's ID token — this one is signed by us, scoped to us, expires in 8 hours).
7. Frontend stores the Vachanam JWT in `localStorage` and includes it as `Authorization: Bearer <jwt>` on every subsequent API call.

### 5.3 What's inside the Vachanam JWT

```json
{
  "sub": "<user.id>",
  "email": "vinay@example.com",
  "role": "super_admin | org_admin | receptionist",
  "org_id": "<uuid or null>",
  "branch_ids": ["<uuid>", "<uuid>"],
  "is_admin": false,
  "iat": 1779500000,
  "exp": 1779528800,
  "jti": "<random uuid>"
}
```

- Signed with HS256 using `JWT_SECRET` (a 32-byte random string generated by `openssl rand -hex 32` and stored in env var)
- `exp` = issue time + 8 hours
- `jti` is a unique ID for THIS specific token — enables revoking just one token without rotating the secret

### 5.4 Session timeout (auto-logout)

Two independent timeouts:

**Hard timeout — 8 hours (JWT `exp`)**
After 8 hours, the token is rejected by the backend regardless of activity. Covers a full clinic shift but caps damage if a device is stolen overnight.

**Idle timeout — 30 minutes (frontend)**
A React hook (`useIdleTimeout`) listens for mouse, keyboard, and touch events. If 30 minutes pass with no activity:
1. Clear the JWT from `localStorage`
2. Redirect to `/login`
3. Show a non-alarming message: "Session expired due to inactivity. Please sign in again."

Uses `document.visibilityState` to pause the timer when the tab is in the background, so the receptionist doesn't get kicked out for switching tabs.

**Why two timeouts?** Hard timeout protects against long-term device theft. Idle timeout protects against momentary unattended device exposure (left phone on counter while attending a patient).

### 5.5 Manual logout

`POST /auth/logout` adds the JWT's `jti` to a Redis set called `revoked_jwts:<jti>` with TTL equal to the remaining `exp - now` time. The `AuthMiddleware` checks this set on every request. A revoked token is rejected even though its signature is still valid and not yet expired.

The frontend clears `localStorage` and redirects, regardless of whether the backend call succeeds (so the user can always log out, even offline).

### 5.6 Brute-force defense on login

- `POST /auth/google` is rate-limited to 5 attempts per minute per IP address.
- After 5 consecutive Google ID token verification failures from one IP within 10 minutes, the IP is blocked for 1 hour (entry in Redis set `blocked_ips`).
- Every failed login is written to `audit_log` with `action="user.login.failure"`, the attempted email, and the IP address.

This protects against credential stuffing — attackers who buy leaked Google passwords from breaches and try them in bulk.

### 5.7 What happens if the JWT secret leaks

- All issued JWTs become forgeable
- Action: rotate `JWT_SECRET` env var, restart backend, all users forced to re-login
- Audit log shows everything done since the leak — used to assess impact
- Detection: leaked-credential-scanning service (GitGuardian free tier) on the GitHub repo

---

## 6. Rate limiting (plain English)

Rate limiting answers the question: "how many requests can ONE user or ONE IP make in a given window before we slow them down?"

### 6.1 Why we need it

Without rate limits:
- A bug in the receptionist app could DDoS our own backend (one client polling every 100ms)
- An attacker who steals a JWT can drain our Razorpay quota in seconds (Razorpay throttles us at 100 orders/min)
- An attacker spamming `/auth/google` with fake tokens uses our quota with Google
- An attacker spamming OpenAI fallback runs up our API bill

### 6.2 How it works

Library: `slowapi` (FastAPI-compatible wrapper over `limits`). Storage: Redis (so rate counters are shared across all backend workers).

Key function — what makes one "user" for counting purposes:

```python
def key_func(request):
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"], options={"verify_exp": False})
            return f"user:{payload['sub']}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"
```

If the request has a valid-looking JWT, count by `user_id`. Otherwise count by IP. This way one shared clinic IP doesn't get throttled because multiple staff are using the app at once.

### 6.3 Per-endpoint limits

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /auth/google` | 5/min per IP | Credential stuffing protection |
| `POST /api/create-order` | 10/min per user | Razorpay caps us at 100/min globally; this leaves headroom for 10 concurrent users |
| `POST /api/verify-payment` | 30/min per user | Modal flow may retry; needs headroom |
| `POST /webhook/whatsapp` | 1000/min per IP | Meta bursts during high-traffic moments |
| `POST /webhook/razorpay` | 100/min per IP | Razorpay can retry webhooks |
| `GET /queue/{branch}/today` | 60/min per user | Receptionist app polls every 30 seconds |
| `PATCH /queue/{branch}/token/*/attend` | 60/min per user | Realistic peak: receptionist marks every 1-2 sec during rush |
| `GET /admin/*` | 30/min per user | Admin views are infrequent |
| `GET /dashboard/*` | 30/min per user | Dashboard refreshes maybe every 5 min |
| All other endpoints | 100/min per user (or per IP) | Reasonable default |

### 6.4 What happens when limit is exceeded

Response: HTTP 429 Too Many Requests, with header `Retry-After: <seconds>`. Audit log entry: `action="rate_limit.exceeded"`, with the endpoint and the user/IP.

Frontend shows a non-blocking toast: "Slow down — too many requests. Try again in a few seconds."

### 6.5 Bypass for trusted IPs

Configurable list of trusted IPs (e.g., Vinay's office for testing) in env var `RATE_LIMIT_BYPASS_IPS`. These IPs are not rate-limited.

### 6.6 Cloudflare-level rate limits (Layer 1)

Cloudflare's free tier includes 10,000 free WAF requests per month plus unlimited DDoS protection. We use the managed OWASP Core Rule Set + Bot Fight Mode. These catch attacks before they reach our app — saves us bandwidth and Redis ops.

---

## 7. Attack protection — OWASP top 10 (plain English)

OWASP top 10 is the industry checklist of the 10 most common web vulnerabilities. Here's how we address each.

### A01 — Broken access control
**What it is:** A user accesses data they shouldn't, by guessing URLs or tampering with IDs.

**Our defenses:**
1. Every database query filters by `branch_id` — even if a receptionist guesses another branch's URL, the DB returns zero rows.
2. `branch_guard` middleware checks the URL `branch_id` against the JWT's `branch_ids` list — returns 403 before the query runs.
3. `require_admin` dependency on admin routes — returns 403 if `is_admin=False`.
4. CI test (`tests/edge_cases/test_data_isolation.py`) creates 2 branches, attempts cross-access, asserts 403.

### A02 — Cryptographic failures
**What it is:** Sensitive data exposed because of weak encryption or missing TLS.

**Our defenses:**
1. TLS everywhere — Cloudflare handles TLS 1.2+ at the edge; Render uses Let's Encrypt for internal cert.
2. HSTS header tells browsers "never speak HTTP to this domain" for one year.
3. JWTs signed with HS256 + 32-byte random secret.
4. Database disk encryption (Neon default).
5. Passwords not stored at all (Google OAuth).
6. Patient phone numbers logged as `phone[-4:]` only (last 4 digits).

**Not in scope for MVP:** application-level field encryption of patient phone/name. Acceptable risk because Neon's disk encryption + access controls + audit log + branch isolation meet DPDP's "reasonable security safeguards" standard. Upgrade path: introduce `crypto_service.py` with AES-GCM when moving to Scale-ready posture.

### A03 — Injection attacks
**What it is:** Attacker sends input that becomes code (SQL injection, XSS, command injection).

**Our defenses against SQL injection:**
- 100% of database access goes through SQLAlchemy ORM with parameterized queries
- If raw SQL is ever needed, use `text()` with `:bindparam` syntax — never f-strings
- Code review check: grep for f-string SQL is a CI failure

**Our defenses against XSS:**
- React auto-escapes all text content by default
- Content Security Policy header blocks inline scripts and only allows specific external script sources (`checkout.razorpay.com`, `accounts.google.com`)
- For any markdown rendering (doctor notes etc.), use `DOMPurify` to sanitize before `dangerouslySetInnerHTML`
- The voice agent's `tts_sanitizer.py` strips markdown before sending to Sarvam TTS (not a security defense, but related)

**Our defenses against command injection:**
- No `subprocess.shell=True` anywhere
- No `eval()`, no `exec()`, no dynamic imports of user-controlled strings

### A04 — Insecure design
**What it is:** Security flaws that come from how the system was designed, not just how it was coded.

**Our defense:** This entire spec. Threat model documented in Section 3 before any security code is written.

### A05 — Security misconfiguration
**What it is:** Defaults left enabled (admin/admin login), debug pages exposed, verbose error messages.

**Our defenses:**
1. `SecurityHeadersMiddleware` adds CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy to every response.
2. In production (`APP_ENV=production`), FastAPI `/docs` and `/redoc` are disabled — attackers can't enumerate our API surface.
3. Error responses in production return generic messages — never raw stack traces.
4. Cloudflare is configured to block common bad paths (`.env`, `.git/`, `wp-admin/`, `.DS_Store`).

### A06 — Vulnerable & outdated components
**What it is:** Using libraries with known CVEs.

**Our defenses:**
1. `requirements.txt` and `package-lock.json` pin exact versions
2. GitHub Dependabot enabled — opens PRs for security updates weekly
3. Monthly manual review: `pip-audit` for Python, `npm audit` for frontend
4. Major framework upgrades (FastAPI, React, etc.) reviewed quarterly

### A07 — Identification & authentication failures
**What it is:** Weak passwords, session fixation, account-takeover via brute force.

**Our defenses:**
- No passwords to be weak (Google OAuth)
- JWTs short-lived (8h) and revocable (`jti` in Redis revocation set)
- Login rate-limited 5/min/IP + 1h IP block after 5 failures
- `jti` is a random UUID — not session-fixation-able

### A08 — Software & data integrity failures
**What it is:** Trusting code/data without verification (compromised CI/CD, malicious dependencies).

**Our defenses:**
- Lock files committed
- Dependabot for known-bad versions
- Razorpay & Meta webhooks signature-verified before any DB write
- LiveKit API calls signed with our `LIVEKIT_API_SECRET`
- No `pip install --pre` ever

### A09 — Security logging & monitoring failures
**What it is:** Not knowing you've been breached because nothing was logged.

**Our defenses:**
1. `audit_log` table (append-only, see Section 8) captures all sensitive actions
2. `structlog` JSON output streamed to Render + Fly log aggregators
3. UptimeRobot pings `/health` every 2 minutes — SMS alerts if down
4. Quarterly review: random sample of 50 audit log entries to detect anomalies

### A10 — Server-side request forgery (SSRF)
**What it is:** Attacker makes our server fetch URLs they control, abusing our trust.

**Our defenses:**
- No endpoint accepts a URL from user input and fetches it
- All outbound HTTP calls go to known endpoints (Razorpay, Meta, Google, Sarvam, LiveKit) with hardcoded base URLs in `settings`
- If we ever need user-supplied URLs (e.g. webhook receivers), validate against an allowlist

---

## 8. Audit logging (plain English)

### 8.1 What gets logged

We log every action that touches PII, money, or org-level configuration. We do NOT log every API call (too noisy, too expensive). Specifically:

**User actions:**
- `user.login.success` — who logged in, from what IP
- `user.login.failure` — what email was attempted, from what IP
- `user.logout` — who logged out
- `user.jwt.revoked` — when a token was added to the revocation list

**Token / booking actions:**
- `token.attend` — receptionist marked a patient as attended
- `token.no_show` — receptionist marked no-show
- `token.cancel` — manual cancel

**Doctor actions:**
- `doctor.cancel_day` — doctor cancelled an entire day
- `doctor.add_tokens` — doctor raised daily limit

**Payment actions:**
- `payment.order.create` — order created at Razorpay
- `payment.verify.success` — signature verified
- `payment.verify.fail` — signature mismatch (attack indicator)

**Admin actions:**
- `admin.view_org` — Vinay viewed a specific org's data
- `admin.view_revenue` — Vinay viewed revenue
- `admin.user.create` — new user added
- `admin.user.role_change` — role changed (privilege escalation requires review)

**Security events:**
- `branch.access_denied` — JWT user tried to access a branch they don't have
- `rate_limit.exceeded` — too many requests
- `webhook.signature_mismatch` — Razorpay or Meta webhook with bad signature

### 8.2 What does NOT get logged

- Successful `GET /queue/today` requests — too noisy, normal usage
- Static asset requests (`/static/*`)
- Health checks (`/health`)
- Patient PII inside the log message (only IDs and last-4 phone)
- Full request bodies (only the action + resource IDs)

### 8.3 Schema

```python
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    success: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
```

### 8.4 Append-only enforcement

The application code never updates or deletes audit log rows. To enforce this beyond convention, the production DB user (`vachanam_app`) is granted only `INSERT` and `SELECT` on `audit_log` — not `UPDATE` or `DELETE`. This is set up in the Phase 10 prod database initialization script.

### 8.5 How auditing is wired into routes

A decorator wraps every sensitive route:

```python
@router.patch("/{branch_id}/token/{token_id}/attend")
@audit("token.attend", resource_type="token")
async def mark_attended(branch_id: str, token_id: str, ...):
    ...
```

The decorator pulls `user_id`, `ip_address`, `user_agent` from the request context, then writes the audit row in a background task (so audit failure can never block the user's request).

### 8.6 How auditing is queried

Vachanam admin dashboard (Phase 8) has an Audit tab:
- Filter by user, branch, action type, date range, success/failure
- "Who marked Token X as no-show" lookup
- "Show all access denials in last 7 days" anomaly detection

### 8.7 Retention

Audit log is kept for 7 years (longer than the 2-year retention for active booking data). This matches typical Indian medical record retention requirements even though we don't store medical records — it's the safer default for legal discovery.

---

## 9. Privacy policy & DPDP compliance (plain English)

### 9.1 The DPDP Act in two paragraphs

India's Digital Personal Data Protection Act of 2023 makes any company that decides how to use Indian citizens' personal data a "Data Fiduciary" with specific obligations: get consent before collecting, only use data for the stated purpose, keep it secure, let users access/correct/delete their data, and report breaches to the Data Protection Board within 72 hours.

Vachanam handles patient names, phones, and complaint summaries on behalf of clinics. Legally, the clinic is the primary Data Fiduciary and Vachanam is the "Data Processor" — but in practice both share liability. Our security and policy posture must be good enough to protect both.

### 9.2 Privacy policy contents

Self-hosted at `app.vachanam.in/privacy` (also linked from `vachanam.in`). Covers:

1. **Who we are** — Vachanam, Hyderabad, founder Vinay Rongala, contact `hello@vachanam.in`, grievance contact `privacy@vachanam.in`
2. **Data we collect**
   - Patient: name, phone, complaint summary (one-line), appointment timestamps
   - Doctor: name, WhatsApp number, specialization, working hours
   - Staff (receptionist, owner): email, name, role
   - Voice call recordings (90-day retention only)
3. **Why we collect** — book appointments, send confirmations, route callers to the right doctor, generate analytics for the clinic owner, send invoices, comply with law
4. **Legal basis** — DPDP Act 2023: legitimate business interest for core booking functions; consent required for marketing
5. **Who sees the data**
   - The patient's chosen clinic (owner + that clinic's staff only)
   - The specific doctor the patient is booked with
   - Vachanam staff for technical support — only when troubleshooting, audit-logged
6. **Third-party data processors** — fully named with links to their privacy policies:
   - Sarvam AI (speech-to-text and text-to-speech)
   - Google (calendar sync; OAuth login)
   - Meta (WhatsApp messaging)
   - Razorpay (payment processing)
   - Neon (database hosting in Singapore)
   - Upstash (Redis cache)
   - LiveKit (voice infrastructure)
   - Fly.io (voice agent hosting)
   - Render (backend API hosting)
7. **Retention periods**
   - Active bookings: 2 years from last activity
   - Voice call recordings: 90 days
   - Audit log: 7 years
   - Deleted account: PII purged within 30 days; audit log retained
8. **Your rights under DPDP** — access (request a copy), correction, erasure (right to be forgotten with exceptions), grievance (email `privacy@vachanam.in`, 7-day SLA)
9. **Children** — patients under 18 may only book via parent/guardian; we don't separately collect minor data
10. **Cookies** — only essential cookies (auth JWT). No analytics, no advertising, no third-party tracking
11. **Updates to this policy** — 30 days notice via email and WhatsApp before any change
12. **Effective date** — set when published

### 9.3 DPDP-specific obligations mapped to implementation

| DPDP obligation | How we comply |
|---|---|
| Notice + free consent | Privacy policy linked from signup; clinic owner must accept before subscribing; call recording starts with "this call is recorded for booking purposes" |
| Purpose limitation | Data used only for booking + analytics shown to the owning clinic; never sold; never used to train AI models on patient data |
| Data minimization | Calendar event stores first-name only + last-4-digits of phone; logs strip full phone; no medical-record-level data stored |
| Accuracy | Owner/receptionist can edit patient records via PWA |
| Storage limitation | Retention policy enforced by daily job `data_retention.py` (Phase 6+ scope) |
| Reasonable security | This entire spec |
| Grievance officer | `privacy@vachanam.in` → Vinay (founder = DPO for MVP); 7-day SLA |
| Breach notification | 72-hour runbook (Section 10) |
| DPO contact | In privacy policy; Vinay's name + email + admin phone |

**No formal DPO appointment** in MVP. DPDP requires DPO only for "Significant Data Fiduciary" status — threshold not yet officially set by central government but expected around 50,000 users. Vinay acts as de facto DPO until SDF threshold triggers.

### 9.4 Data subject rights — how a patient exercises them

A patient who wants to access, correct, or delete their data sends an email to `privacy@vachanam.in`. Process (manual for MVP, automated later):

1. Vinay verifies identity (patient sends a photo of ID, confirms phone via OTP)
2. Vinay runs a script that queries by phone number across `patients`, `tokens`, `calls`, `followup_tasks` for the requested branch
3. Within 7 days: return data export (JSON), apply corrections, OR delete and confirm
4. Audit log entry: `action="data_subject_request"`, success=true, with anonymized request_id

When request volume justifies it (probably >10/month), build a self-service portal.

---

## 10. Infrastructure security (plain English)

### 10.1 TLS

All traffic encrypted in transit. Cloudflare terminates TLS 1.2+ at the edge; Render uses Let's Encrypt for its internal TLS. HSTS header (`Strict-Transport-Security: max-age=31536000; includeSubDomains`) tells browsers to refuse HTTP for one year.

### 10.2 Secrets management

| Secret | Lives in | Rotation |
|---|---|---|
| `JWT_SECRET` | Render env var (production), `.env` (local) | Yearly, or immediately on suspected leak |
| `DATABASE_URL` | Render env var with Neon pooler URL | Quarterly |
| `REDIS_URL` | Render env var with Upstash URL | Quarterly |
| `RAZORPAY_KEY_SECRET` | Render env var | When live keys are issued |
| `RAZORPAY_WEBHOOK_SECRET` | Render env var | When set in Razorpay dashboard |
| `META_ACCESS_TOKEN` | Render env var | Permanent (system user token) |
| `META_APP_SECRET` | Render env var | Permanent |
| `LIVEKIT_API_SECRET` | Render + Fly env var | Quarterly |
| `SARVAM_API_KEY` | Render + Fly env var | Yearly |
| `OPENAI_API_KEY` | Render + Fly env var | Yearly |
| `GEMINI_API_KEY` | Render + Fly env var | Yearly |
| `google-service-account.json` | Render Secret File mounted at `/etc/secrets/`, Fly secret file | Yearly, or on suspected leak |

`.env` is in `.gitignore`. CI check: `git log --all -p | grep -iE "rzp_live|API_SECRET|ACCESS_TOKEN" | head` must return empty before any deploy.

### 10.3 FastAPI hardening

```python
# backend/main.py
app = FastAPI(
    title="Vachanam API",
    version="1.0.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
    lifespan=lifespan,
)
```

In production, `/docs`, `/redoc`, and `/openapi.json` return 404 — attackers can't enumerate our API surface.

### 10.4 Container hardening

Dockerfile changes:

```dockerfile
FROM python:3.11-slim

# create non-root user
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app backend/ backend/
COPY --chown=app:app alembic/ alembic/
COPY --chown=app:app alembic.ini .

USER app

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

Container runs as `app` (not root). If an attacker breaks out of Python and gets shell, they can't escalate to root in the container.

### 10.5 Security headers middleware

```python
# backend/middleware/security_headers.py
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://checkout.razorpay.com https://accounts.google.com; "
            "frame-src https://api.razorpay.com https://accounts.google.com; "
            "connect-src 'self' https://api.razorpay.com; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        return response
```

Each header explained:
- **HSTS:** force HTTPS for 1 year
- **X-Content-Type-Options nosniff:** browser must not guess content types
- **X-Frame-Options DENY:** prevents our pages from being embedded in iframes (clickjacking defense)
- **Referrer-Policy:** don't leak our URLs to external sites in `Referer` header
- **Permissions-Policy:** explicitly deny access to geolocation, mic, camera (we don't use them; deny stops compromised JS from sneaking access)
- **CSP:** the big one — whitelist of allowed script sources. Inline scripts blocked. Razorpay + Google explicitly allowed. Any XSS attempt fails because the malicious script can't load from `evil.com`.

### 10.6 CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],   # exact URL, not wildcard
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

Wildcard origins (`*`) are forbidden because `allow_credentials=True` requires exact origin match per CORS spec. Even local dev uses an exact list: `["http://localhost:5173", "http://localhost:3000", "https://app.vachanam.in"]`.

---

## 11. Breach response runbook (plain English)

Stored at `docs/runbooks/breach-response.md`. Drilled twice a year as a tabletop exercise (Vinay simulates a breach scenario and walks through the steps).

### 11.1 The 5 steps when a breach is suspected

1. **Detect** — Alert sources: Sentry/log anomaly (e.g. spike in 403s on data-isolation endpoints), customer report, vendor notification (e.g. Razorpay tells us a webhook secret leaked), abnormal `audit_log` activity. Triage within 1 hour: is this a real breach, a false alarm, or unclear?

2. **Contain** — Stop the bleeding before investigating:
   - If JWT compromise suspected: clear the Redis revocation set, rotate `JWT_SECRET`, restart backend → all users force-logged-out
   - If DB compromise suspected: rotate Neon credentials, pause writes by setting backend to read-only mode (env flag `READ_ONLY_MODE=true`)
   - If webhook secret leaked: rotate `RAZORPAY_WEBHOOK_SECRET` or `META_APP_SECRET` in respective dashboards + update env vars
   - If a specific user account compromised: add their `jti` to revocation set, disable Google OAuth `google_sub` for that user

3. **Assess** — Query `audit_log` to determine scope:
   - Which users/branches were affected
   - What data was accessed (which resource types, how many records)
   - Earliest sign of compromise (timeline)
   - Whether PII was exposed (changes notification obligations)

4. **Notify** — Within 72 hours of confirmed breach involving personal data:
   - **Data Protection Board of India** — via `dpb.gov.in` per DPDP Rules (to be finalized; format expected: incident summary, scope, mitigation, contact)
   - **Affected clinic owners** — email + WhatsApp with: what happened, what data was involved, what we're doing, what they should do
   - **Affected patients** — if their PII was exposed, WhatsApp notification with: what happened (in plain Telugu/Hindi/English), no action required from them unless they want to delete their data
   - Public statement on `vachanam.in/security` if breach is large enough to warrant transparency

5. **Remediate + Report** — Patch root cause within 7 days. Post-mortem document at `docs/incidents/YYYY-MM-DD-<slug>.md` covering: timeline, root cause (5-whys), what was lost, what was fixed, what we changed to prevent recurrence. Shared with all clinic owners within 14 days. Inform Data Protection Board of remediation.

### 11.2 Specific scenarios pre-rehearsed

| Scenario | First action | Notification required? |
|---|---|---|
| JWT secret leaked in GitHub commit | Rotate secret, force all logout | Yes if commit was public for >1 hour |
| One receptionist's account compromised (phishing) | Disable that user, force their JWT revoke | No (not a data breach; one account) |
| Database read-only access leak (e.g. sandboxed analytics user) | Rotate that role's password, audit query log | Likely yes; assess query log scope |
| Webhook secret leaked | Rotate at vendor, redeploy with new env var | No (no PII access via webhook signing) |
| Voice call recording accidentally exposed via misconfigured Sarvam storage | Delete exposed recordings, contact Sarvam, audit access log | Yes if any patient PII in recordings was downloaded |
| Cross-tenant data leak (Branch A sees Branch B data) | Disable affected endpoint, deploy patch, query affected logs | Yes — file with DPB, notify both branches' owners |

---

## 12. Testing strategy

### 12.1 Automated security tests

| Test file | What it verifies |
|---|---|
| `tests/security/test_rate_limit.py` | 6th call to `/auth/google` in 60s returns 429; trusted IP bypass works |
| `tests/security/test_jwt.py` | Expired token → 401; tampered signature → 401; revoked `jti` → 401; missing token → 401 |
| `tests/security/test_headers.py` | Every endpoint returns CSP, HSTS, X-Frame-Options, etc. |
| `tests/security/test_cors.py` | Request from unlisted origin → blocked; OPTIONS preflight returns correct headers |
| `tests/security/test_audit_log.py` | Login writes a row; failed login writes a row with `success=False`; payment verify writes a row |
| `tests/security/test_injection.py` | SQL injection attempt in `name` field → stored as literal string, no execution; XSS payload in patient name → escaped on read |
| `tests/security/test_admin_only.py` | Non-admin JWT hitting `/admin/*` → 403 |
| `tests/security/test_csp.py` | `frame-ancestors 'none'` etc. — parse CSP header and assert directives |
| `tests/edge_cases/test_data_isolation.py` | (already planned Phase 4) Branch A user cannot read Branch B data |
| `tests/security/test_secrets_not_in_repo.py` | `git log --all -p | grep -iE "rzp_live|API_SECRET"` returns empty |

All run in CI on every pull request. Failure blocks merge.

### 12.2 Manual security review (pre-release)

Before each production release:
- Run **OWASP ZAP** baseline scan locally against `localhost:8000` (free, automated active scan)
- Run **nikto** against the public URL — checks for common misconfigurations
- Run **nmap -sV** against the public IPs — should only show 443 open
- Manual review: log a sample of 50 audit log entries from the past week, look for anomalies

### 12.3 Quarterly review

- Run `pip-audit` and `npm audit` — patch any CVEs
- Review all OAuth-granted apps in Google Cloud Console — revoke unused
- Review Render + Fly + Cloudflare access logs for the past 90 days — anomaly check
- Test the breach response runbook end-to-end (simulated breach, follow all 5 steps, time it)
- Review this spec — update for any new components added

### 12.4 Bug bounty (post-MVP)

Once we have 25+ paying clinics, consider listing on Bugcrowd or HackerOne with a small reward pool (e.g., ₹5k-50k per finding). Until then, accept disclosures at `security@vachanam.in` with a hall-of-fame thank-you.

---

## 13. Implementation phasing

This spec slots in as **Phase 4.5** between Phase 4 (Backend Core) and Phase 5 (WhatsApp). Reasoning:

- Phase 4 builds the JWT auth middleware, queue API, and `main.py`. These are the foundations security relies on.
- Phase 5+ adds new routes (WhatsApp webhooks, dashboards). Every new route needs to inherit our security defaults. The `audit` decorator, `rate_limit` decorator, `security_headers` middleware must exist before Phase 5 endpoints are written.

**Phase 4.5 estimated effort:** 3-4 days. Breakdown:

| Day | Work |
|---|---|
| Day 1 | `SecurityHeadersMiddleware` + CORS hardening; `JWT_SECRET` rotation tested; idle timeout React hook; FastAPI prod-docs disable; container non-root user. Tests for headers + CORS. |
| Day 2 | `slowapi` integration; per-endpoint rate limits; Redis-backed counters; failed-login IP block; tests for rate limit + login brute force. |
| Day 3 | `audit_log` table + Alembic migration; `@audit` decorator; wire into existing routes (login, payments, queue); query interface for admin; tests for audit. |
| Day 4 | Privacy policy page (`/privacy`); breach runbook document; Cloudflare account setup + DNS + WAF managed rules; Dependabot enable; CI checks for secrets in repo. Spec self-review + manual ZAP scan. |

After day 4: update STATUS.md, mark Phase 4.5 done in ROADMAP.md, commit, move to Phase 5.

---

## 14. Open questions / explicitly deferred

These are deliberate trade-offs for MVP. Each has a documented path forward.

| Item | MVP decision | When to revisit |
|---|---|---|
| Field-level encryption of patient phone/name | No (rely on Neon disk encryption + branch isolation + audit) | Scale-ready posture, ~50 clinics |
| Two-factor authentication beyond Google | No (Google's 2FA delegated) | When customers ask for SOC2 |
| Formal DPO appointment | No (Vinay = de facto DPO) | Significant Data Fiduciary threshold reached |
| WAF beyond Cloudflare free | No (free tier sufficient) | When abuse traffic exceeds free quota |
| Penetration test by third party | No (DIY ZAP + nikto + nmap) | Pre-Series-A or first SOC2 audit |
| Bug bounty program | No (accept disclosures only) | 25+ paying clinics |
| Per-row access control beyond branch_id | No (branch_id sufficient for current data model) | When patient cross-clinic histories become a feature |
| Encrypted log storage | No (Render/Fly built-in log retention sufficient) | When logs themselves become a target (likely never for MVP) |
| HSM-backed JWT signing key | No (env var sufficient) | SOC2 audit prerequisite |
| Web Application Firewall (full) | No (Cloudflare managed rules enough) | Active attack incident triggers upgrade |

---

## 15. Acceptance criteria (Phase 4.5 done = all of these green)

```
[ ] SecurityHeadersMiddleware applies CSP, HSTS, X-Frame, X-Content-Type, Referrer, Permissions on every endpoint
[ ] FastAPI /docs returns 404 when APP_ENV=production
[ ] Container runs as non-root user (verified: `docker exec <id> whoami` → app)
[ ] CORS rejects requests from non-allowed origins (verified by curl)
[ ] CORS preflight returns correct headers (curl -X OPTIONS)
[ ] JWT lifecycle works: issue, decode, expire, revoke
[ ] React useIdleTimeout hook implemented and tested manually (30 min no activity → forced login)
[ ] Per-endpoint rate limits enforced (verified by hitting /auth/google 6× in 1 min → 429)
[ ] Failed login attempts logged to audit_log; 5 failures from 1 IP → 1h block
[ ] audit_log table exists; migration applied; rows visible in psql
[ ] @audit decorator wraps all sensitive routes; rows appear when actions performed
[ ] Privacy policy page renders at /privacy with all 12 sections
[ ] Breach response runbook saved at docs/runbooks/breach-response.md
[ ] Cloudflare account set up; WAF managed rules enabled; Bot Fight Mode on
[ ] Dependabot enabled on GitHub repo
[ ] All tests in tests/security/ pass in CI
[ ] CI check: secrets-in-repo scan passes
[ ] OWASP ZAP baseline scan run locally; no high/critical findings
[ ] STATUS.md and ROADMAP.md updated to reflect Phase 4.5 complete
```

When all 19 criteria check, Phase 4.5 is complete and we proceed to Phase 5 (WhatsApp).
