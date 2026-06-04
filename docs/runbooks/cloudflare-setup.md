# Runbook: Cloudflare Setup (Phase 10 cutover)

**Owner:** devops-engineer | **Env:** production | **Tier:** Free
**Last reviewed:** 2026-06-04 | **Execute on:** Phase 10 deployment day

---

## Section 1 — DNS records

Add these records in the Cloudflare dashboard under the `vachanam.in` zone.
Set proxy status to **Proxied** (orange cloud) for all A/CNAME records except
the `agent` entry, which can be DNS-only until health-check is verified.

| Subdomain | Type | Value | Proxy | Purpose |
|---|---|---|---|---|
| `vachanam.in` | A | existing host IP (out of scope) | DNS-only | Marketing site — do not touch |
| `api.vachanam.in` | CNAME | `<render-service>.onrender.com` | Proxied | Backend (Render) |
| `app.vachanam.in` | CNAME | `<pages-project>.pages.dev` | Proxied | Frontend PWA (Cloudflare Pages) |
| `agent.vachanam.in` | CNAME | `vachanam-agent.fly.dev` | DNS-only initially | Fly agent health endpoint (optional) |

TTL: Cloudflare managed (auto) for proxied records. Set 300s for DNS-only.

---

## Section 2 — Free-tier security settings (UI clicks)

### 2.1 TLS — Full (Strict)

**Security > SSL/TLS > Overview**

Select **Full (Strict)**.

- **NOT Flexible** — Flexible terminates TLS at Cloudflare edge then sends plain HTTP to Render. Man-in-the-middle risk on the Cloudflare-to-Render leg.
- **NOT Full (non-strict)** — does not verify Render's certificate.
- **Full (Strict)** is the only correct setting: Cloudflare verifies Render's Let's Encrypt cert.

### 2.2 HSTS at edge

**Security > SSL/TLS > Edge Certificates > HTTP Strict Transport Security (HSTS)**

Enable HSTS. Set:
- Max Age Header: **12 months (31536000)**
- Include subdomains: **On**
- Preload: **On** (safe after confirming app + agent subdomains all serve HTTPS)
- No-Sniff Header: **On**

### 2.3 Managed Rules (OWASP CRS subset)

**Security > WAF > Managed rules**

Enable **Cloudflare Managed Ruleset**. On Free tier this activates the managed CRS-derived ruleset. Default action is **Block** for the highest-confidence rules.

No configuration needed beyond enabling — the default ruleset covers OWASP Top 10 injection, XSS, path traversal, and scanner signatures.

See Section 4 for the quota clarification on this product.

### 2.4 Bot Fight Mode

**Security > Bots**

Toggle **Bot Fight Mode: On**.

Challenges likely bots at the edge before they consume backend capacity. No cost. No configuration needed.

### 2.5 "Under Attack" mode (break-glass only)

**Security > Settings > Security Level**

Normal operation: **Medium** (default).

Under active DDoS: change to **I'm Under Attack!** — see Section 6 for when and how.

---

## Section 3 — Custom firewall rules (5 rules, Free tier limit)

**Security > WAF > Custom rules > Create rule**

These 5 rules block common probe paths that have zero legitimate use in Vachanam.

### Rule 1 — Block .env probe
**Rule name:** Block .env probe
**Expression:** `(http.request.uri.path contains "/.env")`
**Action:** Block

### Rule 2 — Block .git directory probe
**Rule name:** Block .git probe
**Expression:** `(http.request.uri.path contains "/.git/")`
**Action:** Block

### Rule 3 — Block WordPress admin probe
**Rule name:** Block wp-admin probe
**Expression:** `(http.request.uri.path contains "/wp-admin")`
**Action:** Block

### Rule 4 — Block WordPress login probe
**Rule name:** Block wp-login probe
**Expression:** `(http.request.uri.path contains "/wp-login.php")`
**Action:** Block

### Rule 5 — Block macOS metadata file probe
**Rule name:** Block .DS_Store probe
**Expression:** `(http.request.uri.path contains "/.DS_Store")`
**Action:** Block

These 5 rules exhaust the Free tier custom rule quota. If a 6th rule is needed,
upgrade to the $20/month Pro tier or replace rule 5 with the higher-value target.

---

## Section 4 — Free-tier quota check

| WAF product | Free tier quota | Our usage |
|---|---|---|
| Managed Ruleset (OWASP CRS) | **Unlimited** — no request cap | Enabled. Covers all inbound traffic. |
| Custom Rules | 5 rules maximum | All 5 used (Section 3). |
| WAF Rate Limiting Rules | 10,000 requests/month cap | **NOT used.** We use `fastapi-limiter` (Redis-backed) at the app layer for rate limiting. No Cloudflare Rate Limiting Rules configured. |

Key point: the "10k/month" figure in older Cloudflare docs refers exclusively to the
**WAF Rate Limiting Rules** product, not to the managed ruleset evaluation. The managed
CRS runs on every request at no count against any quota.

---

## Section 5 — Phase 10 cutover sequence

Execute in this order on deployment day:

1. **Deploy backend to Render** — confirm `https://<service>.onrender.com/health` returns 200.
2. **Deploy frontend to Cloudflare Pages** — confirm `https://<project>.pages.dev/` loads.
3. **Deploy agent to Fly.io** — confirm `flyctl status` shows `min_machines_running=1`.
4. **Add DNS records** (Section 1) — CNAME for `api.` and `app.` set to Proxied.
5. **Set TLS to Full (Strict)** (Section 2.1).
6. **Enable HSTS** (Section 2.2) — do this ONLY after confirming HTTPS works end-to-end.
7. **Enable Managed Rules** (Section 2.3) and **Bot Fight Mode** (Section 2.4).
8. **Add 5 custom firewall rules** (Section 3).
9. **Verify post-cutover:**
   - `curl -I https://api.vachanam.in/health` → `HTTP/2 200`, `strict-transport-security` header present.
   - `curl -I https://app.vachanam.in/` → `HTTP/2 200`.
   - `curl -I https://api.vachanam.in/.env` → `HTTP/2 403` (blocked by rule 1).
   - `curl -I https://api.vachanam.in/.git/config` → `HTTP/2 403` (blocked by rule 2).
   - Cloudflare Security > Overview — confirm managed rules are triggering on scanner traffic within first hour.
10. **Set UptimeRobot monitors** — `https://api.vachanam.in/health` (2-min interval, SMS to ADMIN_PHONE).

Rollback: DNS changes propagate within Cloudflare's managed TTL (~1 min). To revert, delete or re-point the CNAME record. Render/Fly apps remain deployed; only DNS routing changes.

---

## Section 6 — Under Attack 1-pager

### When to engage

Use **I'm Under Attack** mode when:
- UptimeRobot fires a DOWN alert for `api.vachanam.in` AND Render shows normal CPU/memory.
- Render logs show thousands of requests/second from distributed IPs.
- Backend `/health` responds from inside Render but `curl` from outside times out.

This indicates volumetric DDoS absorbed at the edge — exactly what this mode is for.

### How to engage

1. Log in to Cloudflare dashboard.
2. **Security > Settings > Security Level > I'm Under Attack!**
3. All visitors receive a 5-second JS challenge page before reaching the backend.
4. Legitimate browsers pass. Bots and raw HTTP clients are blocked.

### What to monitor during attack

- Cloudflare **Security > Overview** — watch "Threats blocked" counter climb.
- Cloudflare **Analytics > Traffic** — verify origin requests drop while edge requests spike.
- Render logs — confirm backend request volume returns to baseline.
- UptimeRobot — confirm monitor recovers to UP.

### When to disengage

After 30-60 minutes of sustained normal traffic with no new anomaly, revert:
**Security > Settings > Security Level > Medium**

Leaving "Under Attack" on permanently degrades UX for real patients (5s delay on every visit).

### Escalation

If Cloudflare edge is also overwhelmed (rare — Cloudflare handles 100+ Gbps on Free):
- File a Cloudflare support ticket (even Free tier has Community support).
- Contact Render support if origin is separately targeted.
- Post incident update to STATUS page.
