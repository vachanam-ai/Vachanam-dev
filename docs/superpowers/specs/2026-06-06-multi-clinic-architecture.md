# Vachanam -- Multi-Clinic Architecture (10-Clinic Scale)

**Date:** 2026-06-06
**Author:** Vinay Rongala (spec), Manager (coordination), Brainstormer (analysis)
**Status:** Approved -- pending Vobiz support confirmation on 4 open questions
**Posture target:** 10 clinics across 10 Indian cities, 200-800 calls/day total, single founder operating
**Slots into:** Phase 9 (Subscriptions + Onboarding) and Phase 10 (Deployment)

---

## 1. Goal and scope

Vachanam currently handles one clinic (one DID, one branch, one doctor). This spec defines the architecture to onboard 10 clinics across 10 Indian cities -- each with its own local phone number, doctors, schedules, and patients -- sharing a single infrastructure stack operated by one founder.

**In scope:**
- Telephony architecture (shared trunk, N DIDs, routing)
- Database isolation (branch_id scoping at 10-clinic scale)
- Connection pool tuning for concurrent calls
- Agent concurrency and state isolation
- Provisioning workflow per new clinic
- Pricing math and margin analysis at 10 clinics
- Failure modes and disaster recovery
- Migration path from current single-clinic state

**Out of scope:**
- WhatsApp integration (deferred to MVP2)
- Multi-region redundancy (evaluate at 50 clinics)
- Custom AI model training per clinic
- White-label branding per clinic

---

## 2. Architecture diagram

```
                     PATIENT CALLS CLINIC DID
                              |
                    +---------v-----------+
                    |   Vobiz Upstream     |
                    |   (Indian carrier)   |
                    |   MA_WJ7ZPSWT        |
                    +---------+-----------+
                              |  SIP INVITE
                    +---------v-----------+
                    |   Shared Vobiz Trunk |
                    |   concurrent: 30     |
                    |   N DIDs linked via  |
                    |   trunk_group_id     |
                    +---------+-----------+
                              |  SIP -> WebSocket
                    +---------v-----------+
                    |   LiveKit Server     |
                    |   (Fly.io bom Mumbai)|
                    |   self-hosted prod   |
                    |   unlimited concurr  |
                    +---------+-----------+
                              |  Room created
                    +---------v-----------+
                    |   LiveKit SIP Bridge |
                    |   Dispatch Rule:     |
                    |   catch-all ->       |
                    |   voice-assistant    |
                    +---------+-----------+
                              |  Agent dispatched
                    +---------v-----------+
                    |   Vachanam Agent     |
                    |   (VachananAgent)    |
                    |                      |
                    |   sip.trunkPhone     |
                    |   Number attr        |
                    |        |             |
                    |   SELECT id FROM     |
                    |   branches WHERE     |
                    |   did_number = ?     |
                    |        |             |
                    |   branch_id resolved |
                    |   -> clinic context  |
                    |   -> scoped tools    |
                    |   -> Telugu greeting |
                    +---------+-----------+
                              |
              +---------------+---------------+
              v               v               v
     +------------+  +------------+  +------------+
     | Neon PG    |  | Upstash    |  | Sarvam     |
     | (branches, |  | Redis      |  | STT + TTS  |
     |  tokens,   |  | (token     |  | (Telugu/   |
     |  doctors)  |  |  INCR per  |  |  Hindi/    |
     |            |  |  branch+   |  |  English)  |
     | pool_size  |  |  doctor+   |  |            |
     | =10,       |  |  date)     |  |            |
     | max_over   |  |            |  |            |
     | =20        |  |            |  |            |
     +------------+  +------------+  +------------+
```

---

## 3. Component decisions

| Layer | Choice | Rationale | Scaling profile |
|---|---|---|---|
| **Telephony** | Vobiz reseller account MA_WJ7ZPSWT | Only Indian DID provider with SIP streaming at Rs 0.65/min. Partner API for programmatic DID provisioning. | 1 account -> N DIDs. No per-account limit discovered. DID inventory varies by city. |
| **SIP trunk** | 1 shared Vobiz trunk, concurrent_calls_limit raised from 10 to 30 | Fewer trunks = fewer credentials = simpler ops. Split trigger: peak simultaneous calls regularly exceed 25 (70% of 30 limit). | At 10 clinics averaging 4 concurrent calls each, peak should stay under 20. One trunk sufficient. |
| **Agent runtime** | LiveKit Agents on Fly.io bom Mumbai (self-hosted) | LiveKit Cloud Build = 5 concurrent (insufficient at 10 clinics). Ship = $50/mo = 20 concurrent. Self-hosted = unlimited. Fly.io VM = Rs 840/mo shared across all clinics. Saves approx Rs 8,660/mo vs Ship tier overage at 10 clinics. Source: livekit.io/pricing, fly.io/docs/about/pricing. | Apache-2.0 open source. Horizontal scale by adding Fly.io VMs. |
| **Database** | Neon Postgres (Launch plan, $5/mo) with pooler URL | Serverless, auto-suspend on idle. Built-in connection pooler (PgBouncer mode). All clinic data in same DB, isolated by branch_id WHERE clause (CLAUDE.md Rule 1). | Launch plan supports 100 concurrent connections. Pooler URL handles connection multiplexing. |
| **Token locking** | Upstash Redis (free tier, 500K commands/mo) | Atomic INCR per token:{doctor_id}:{branch_id}:{date}. No cross-clinic interference by design (key includes branch_id). | 10 clinics x 50 calls/day x 3 Redis ops/call x 30 days = 45K commands/mo. Well within 500K free tier. |
| **STT/TTS** | Sarvam Saaras v3 / Bulbul v3 | Only viable Telugu STT/TTS. Pay-per-minute. No per-clinic setup. Source: sarvam.ai/api-pricing. | Rs 0.50/min STT + Rs 0.30/min TTS = Rs 0.80/min. Linear scale with call volume. |
| **LLM** | Gemini 2.5 Flash (primary) / GPT-4o mini (fallback) | Best Telugu reasoning. Rs 0.01/min per call. Shared API key across all clinics. Source: aistudio.google.com. | Gemini free tier generous. GPT-4o mini fallback adds resilience. |
| **Calendar** | Google Calendar API v3 (service account) | Free API. Doctors already use Google Calendar. One service account can manage multiple calendars via domain-wide delegation or per-calendar sharing. | No per-clinic cost. Calendar ID stored per doctor in DB. |
| **Hosting** | Fly.io (agent) + Render (backend) + Cloudflare Pages (frontend) | India-region PaaS. Total infra: Rs 840 + Rs 588 + Rs 0 = Rs 1,428/mo. Shared across all 10 clinics. | Fly.io scales with VMs. Render auto-restarts. Cloudflare CDN global. |

---

## 4. Trunk strategy

### Decision matrix: 1 shared trunk vs N per-clinic trunks

| Factor | 1 shared trunk (RECOMMENDED) | N per-clinic trunks |
|---|---|---|
| Credential management | 1 set of SIP credentials | 10 sets -- rotation nightmare |
| LiveKit dispatch rules | 1 catch-all rule | 10 rules, one per trunk |
| Provisioning complexity | Add DID to trunk numbers list | Create new trunk + dispatch rule per clinic |
| Failure blast radius | Trunk down = ALL 10 clinics dead | Trunk down = 1 clinic dead |
| Concurrent call limit | Shared 30-slot pool | Each trunk gets its own limit |
| Monthly cost | 1 trunk fee (amount TBD -- Vobiz question) | 10x trunk fee |
| Ops overhead for 1 founder | Minimal | Unmanageable at 10+ |

**Recommendation:** 1 shared trunk at 10 clinics. The blast-radius downside (all clinics dead on trunk failure) is acceptable because:
1. At 10 clinics, Vachanam has no SLA obligations beyond best-effort (MVP-launch posture per security spec).
2. Vobiz is the ONLY Indian DID provider with SIP streaming -- there is no failover trunk vendor anyway.
3. Splitting to N trunks does NOT reduce Vobiz-upstream failure risk (same upstream carrier).

**Split trigger:** When peak simultaneous calls regularly exceed 25 (70% of the 30-slot concurrent_calls_limit), evaluate splitting into 2-3 trunks grouped by region. The capacity monitor job (Task 8 in implementation plan) will detect this.

---

## 5. DID-to-branch routing (10-step call trace)

This is the critical path that makes multi-clinic work. Each step references existing code.

1. **Patient dials clinic DID** -- e.g., +914066XXXXXX (Hyderabad local number)
2. **Indian carrier routes to Vobiz** -- standard PSTN routing
3. **Vobiz identifies DID on shared trunk** -- matches inbound_destination to LiveKit SIP endpoint
4. **Vobiz sends SIP INVITE to LiveKit** -- via the shared trunk address field (e.g., vachanam-gimml0ao.livekit.cloud)
5. **LiveKit SIP bridge creates room** -- room name auto-generated, SIP participant joined
6. **LiveKit dispatch rule fires** -- catch-all rule dispatches agent named voice-assistant
7. **Agent process wakes** -- agent/agent.py entrypoint (line ~740) receives JobContext
8. **_wait_for_sip_participant()** -- agent/agent.py:82-100 -- waits up to 10s for SIP participant to appear in room
9. **_resolve_branch_from_sip()** -- agent/agent.py:103-150 -- reads sip.trunkPhoneNumber attribute from the SIP participant, queries SELECT id FROM branches WHERE did_number = DID, returns (branch_id, patient_phone)
10. **Branch context loaded** -- SessionState populated with branch_id, all booking tools scoped to that branch via WHERE branch_id = ?. Clinic-specific greeting plays. Call proceeds.

**Key isolation guarantee:** Step 9 is the gate. If the DID is not found in the branches table, ValueError is raised and ctx.shutdown() is called. There is no fallback to a default branch -- unknown DIDs are rejected.

---

## 6. Provisioning workflow per new clinic

Each new clinic requires 11 steps. Some are automated, some require manual intervention (Vobiz KYC is the bottleneck).

| Step | Action | Auto/Semi/Manual | Time estimate | Blocker? |
|---|---|---|---|---|
| 1 | Razorpay payment captured (webhook) | Auto | Instant | No |
| 2 | INSERT Organization + Branch + Doctor rows | Auto | <1s | No |
| 3 | Request Vobiz DID (local number for clinic city) | Semi-auto (API call, needs KYC) | Instant API, 4-24h KYC | **YES** |
| 4 | Vobiz KYC verification | Manual (Vobiz support) | 4-24h | **YES** |
| 5 | Run pre-flight checker (check_vobiz_did_ready.py) | Auto | <5s | Blocks step 6 |
| 6 | Link new DID to shared trunk via LiveKit update_inbound_trunk API | Auto | <2s | No |
| 7 | Update branches.did_number with provisioned DID | Auto | <1s | No |
| 8 | Create Google Calendar for clinic doctors | Semi-auto (service account shares calendar) | <30s | No |
| 9 | Send welcome email to clinic owner | Auto | <5s | No |
| 10 | Configure UptimeRobot monitor for new DID | Semi-auto (API or dashboard) | <2 min | No |
| 11 | Verify first test call | Manual (Vinay dials) | 5 min | No |

**Critical bottleneck:** Steps 3-4 (Vobiz KYC) dominate onboarding time. If KYC is **per-DID** (not per-account), every new clinic adds 4-24h delay. This is the #1 open question to resolve with Vobiz support (see Section 10).

**Mitigation:** Pre-purchase a pool of 5-10 DIDs across target cities during the initial account setup, so KYC is done once for the batch. New clinics draw from the pre-verified pool. Replenish when pool drops below 3.

---

## 7. Concurrency and isolation

### 7.1 LiveKit tier comparison

| Tier | Concurrent participants | Monthly cost | Viable at 10 clinics? |
|---|---|---|---|
| **Build** (current dev) | 5 | Free | No -- 10 clinics could easily have 5+ simultaneous calls |
| **Ship** | 20 | $50/mo (approx Rs 4,200/mo) | Marginal -- peak could exceed 20 |
| **Self-hosted Fly.io** | Unlimited (VM-bound) | Rs 840/mo (shared-cpu-2x) | **Yes -- recommended for production** |

Source: livekit.io/pricing. Self-hosted is Apache-2.0 licensed.

**Decision:** Self-hosted LiveKit on Fly.io bom Mumbai for production. LiveKit Cloud Build tier remains for development/testing.

### 7.2 Redis INCR safety at multi-clinic scale

Redis token keys are namespaced as token:{doctor_id}:{branch_id}:{date}. At 10 clinics:
- Each clinic has independent key space (branch_id is a UUID)
- No cross-clinic token collision is possible by design
- INCR is atomic -- 10 simultaneous calls to 10 different clinics = 10 independent INCR operations, zero contention
- Same-clinic concurrent calls (e.g., 3 patients calling one busy clinic simultaneously) are handled by Redis atomicity, same as single-clinic mode
- Upstash free tier (500K commands/month) is sufficient -- estimated 45K commands/month at 10 clinics

### 7.3 Postgres connection pool tuning

**Current state:** backend/database.py has no explicit pool tuning -- SQLAlchemy defaults apply (pool_size=5, max_overflow=10, total 15 connections).

**Problem:** At 10 concurrent calls, each call opens ~2 DB sessions (branch lookup + booking). Peak = ~20 sessions. Adding backend API traffic (receptionist PWA, dashboard) could push to 25-30.

**Fix:** Add explicit pool tuning to backend/database.py:

    pool_size=10, max_overflow=20, pool_pre_ping=True

Use Neon pooler connection string (PgBouncer mode) for production -- this provides an additional pooling layer between the app and the actual Postgres.

### 7.4 Agent state isolation

Each call gets its own SessionState instance (per agent/session_state.py). At 10 concurrent calls:
- 10 independent SessionState objects in memory
- Each scoped by branch_id resolved in step 9 of the call trace
- No shared mutable state between calls
- LiveKit dispatches each call to a separate agent worker process -- process-level isolation

---

## 8. Failure modes and disaster recovery

| Failure | Impact at 10 clinics | Detection | Recovery | RTO |
|---|---|---|---|---|
| **Vobiz trunk down** | ALL 10 clinics: no inbound calls | UptimeRobot alert (2-min check) | Wait for Vobiz to restore. No failover vendor exists for Indian SIP streaming. Patients hear carrier busy/voicemail. | Dependent on Vobiz -- historically <1h for non-catastrophic outages |
| **Sarvam STT/TTS down** | ALL 10 clinics: agent cannot understand or speak | Agent-level health check + structlog alert | Graceful message: "We are experiencing difficulties, please call back." No STT/TTS alternative for Telugu. | Dependent on Sarvam -- 99.99% uptime claim |
| **Neon Postgres down** | ALL 10 clinics: no bookings, no branch resolution | Agent raises ValueError on branch lookup, Render health check fails | Neon auto-recovers. Daily automatic backups. RPO = 24h. | Neon SLA: <5 min for non-catastrophic |
| **Upstash Redis down** | ALL 10 clinics: no token assignment (booking fails gracefully) | Redis INCR raises ConnectionError, caught by tenacity retry | Upstash auto-recovers. Token counters can be reconstructed from Postgres token table. | <5 min typical |
| **Fly.io VM crash** | ALL 10 clinics: agent process dead, calls drop | Fly.io auto-restart + UptimeRobot | Fly.io auto-restarts VM. Active calls lost (patients redial). | <60s for VM restart |
| **Render backend down** | Dashboard/API unavailable; voice agent unaffected (reads DB directly) | UptimeRobot + Render auto-restart | Auto-restart. No manual intervention. | <60s |
| **Single clinic DID deactivated** | 1 clinic dead, 9 unaffected | Pre-flight checker (run periodically) + patient complaints | Vobiz support ticket. Replace DID from pre-purchased pool if available. | 4-24h (KYC dependent) |
| **Gemini API down** | Degraded: auto-fallback to GPT-4o mini | structlog captures gemini_failed_switching_to_openai | Automatic. No manual intervention. Telugu quality may degrade slightly on GPT-4o mini. | 0 (automatic) |

**Single-vendor risk summary:** Vobiz, Sarvam, and Neon are single points of failure for all 10 clinics. This is **acceptable at 10 clinics** (MVP-launch posture). At 50 clinics, evaluate: (a) secondary SIP provider for failover, (b) Google Cloud STT/TTS as Sarvam backup, (c) Neon read replicas or CockroachDB for DB redundancy.

---

## 9. Pricing math at 10 clinics

### 9.1 Revenue projection (conservative mix)

| Plan | Count | MRR per clinic | Total MRR |
|---|---|---|---|
| Solo (Rs 1,999 + Rs 3/min overage) | 3 | Rs 1,999 base | Rs 5,997 |
| Clinic (Rs 7,999 flat) | 5 | Rs 7,999 | Rs 39,995 |
| Multi (Rs 16,999 flat) | 2 | Rs 16,999 | Rs 33,998 |
| **Total MRR** | **10** | | **Rs 79,990** |

### 9.2 Cost breakdown

**Variable costs (call volume: 300 calls/day avg across 10 clinics, 3.5 min avg):**

| Item | Per-minute rate | Monthly minutes | Monthly cost |
|---|---|---|---|
| Sarvam STT | Rs 0.50/min | 31,500 | Rs 15,750 |
| Sarvam TTS | Rs 0.30/min | 31,500 | Rs 9,450 |
| Vobiz streaming | Rs 0.65/min | 31,500 | Rs 20,475 |
| Gemini 2.5 Flash | Rs 0.01/min | 31,500 | Rs 315 |
| LiveKit VM share | Rs 0.03/min | 31,500 | Rs 945 |
| **Variable subtotal** | **Rs 1.49/min** | | **Rs 46,935** |

Note: 300 calls/day x 3.5 min x 30 days = 31,500 min/month.

**Fixed costs (shared infrastructure, does not scale with clinics):**

| Item | Monthly cost |
|---|---|
| Fly.io bom VM (shared-cpu-2x 1GB) | Rs 840 |
| Render web service (Starter plan) | Rs 588 |
| Neon Postgres (Launch plan) | Rs 420 |
| Upstash Redis | Rs 0 (free tier) |
| Google Calendar API | Rs 0 |
| Cloudflare Pages | Rs 0 |
| UptimeRobot | Rs 0 |
| **Fixed subtotal** | **Rs 1,848** |

**Per-clinic costs:**

| Item | Per clinic/month |
|---|---|
| Vobiz DID number | Rs 1,000 |
| WhatsApp messages (DEFERRED MVP2) | Rs 0 |
| **Per-clinic subtotal** | **Rs 1,000** |

### 9.3 Margin calculation

```
Total Revenue:           Rs  79,990
Variable costs:         -Rs  46,935   (call volume dependent)
Fixed infra:            -Rs   1,848   (shared, does not grow)
Per-clinic DIDs (10x):  -Rs  10,000
------------------------------------------------
Gross margin:            Rs  21,207
Margin %:                     26.5%
```

**Note:** This is a conservative estimate at 300 calls/day. If average drops to 200 calls/day:
- Variable costs drop to Rs 31,290
- Margin improves to Rs 36,852 (46.1%)

If average rises to 500 calls/day:
- Variable costs rise to Rs 78,225
- Margin drops to Rs -10,083 (negative -- overage billing from Solo/Multi plans needed to cover)

**Overage upsell signal:** When a Solo clinic consistently exceeds 100 included minutes or a Clinic plan exceeds 2,100 minutes, the billing system should auto-detect and recommend upgrading. This is a Phase 9 (billing_cycle.py) feature.

---

## 10. Open questions for Vinay (action required)

These questions must be answered before Phase 9 onboarding work begins. Each blocks one or more implementation tasks.

| # | Question | Who to ask | Blocks | Expected timeline |
|---|---|---|---|---|
| 1 | **Is the Vobiz trunk monthly fee per-trunk or per-DID?** If per-DID, 10 DIDs = 10x the fee. If per-trunk, 1 shared trunk = 1x. This changes the cost model by Rs 0-9,000/month. | Vobiz support (support@vobiz.ai or partner dashboard ticket) | Pricing math (Section 9) | 1-3 business days |
| 2 | **Is Vobiz KYC per-account or per-DID?** If per-account, new DIDs are instant after initial KYC. If per-DID, every new clinic adds 4-24h onboarding delay. | Vobiz support | Provisioning workflow (Section 6), DID pre-purchase strategy | 1-3 business days |
| 3 | **Can concurrent_calls_limit be raised self-serve or does it require a support ticket?** Current limit is 10. Need 30 for 10-clinic headroom. | Vobiz support | Trunk strategy (Section 4), capacity planning | 1-3 business days |
| 4 | **Are DIDs linkable to a trunk via API or dashboard-only?** Current provision_vobiz_trunk.py uses LiveKit API to link DIDs. But does Vobiz require separate DID-to-trunk linking on their side? | Vobiz support | Provisioning automation (Task 3 in plan) | 1-3 business days |
| 5 | **Google Calendar: shared service account vs per-clinic OAuth?** Shared service account = simpler (one credential), but requires each doctor to share their calendar with the service account email. Per-clinic OAuth = more setup but standard. | Architecture decision (Vinay + Manager) | Calendar integration (Phase 6) | Internal decision, 30 min |
| 6 | **Regional DID inventory: which 10 cities are target clinics?** Vobiz DID availability varies by city. Some cities may only have 080/040 prefixes. Need city list to verify DID availability. | Vinay (business decision) | DID pre-purchase (Section 6 mitigation) | Vinay decides |
| 7 | **Concurrency upgrade trigger: at what peak simultaneous call count should we alert?** Spec recommends 70% of trunk limit (= 21 of 30). Is this too conservative or too aggressive? | Architecture decision (Vinay + Manager) | Capacity monitor job (Task 8 in plan) | Internal decision, 10 min |

---

## 11. Decision log

### Locked decisions (implemented or approved)

| Decision | Rationale | Date |
|---|---|---|
| 1 shared Vobiz trunk for 10 clinics | Simpler ops, lower cost, acceptable blast radius at MVP scale | 2026-06-06 |
| Self-hosted LiveKit on Fly.io for production | Rs 840/mo vs $50/mo LiveKit Ship. Unlimited concurrency. Apache-2.0. | 2026-06-06 |
| DID-to-branch routing via sip.trunkPhoneNumber | Already implemented in agent/agent.py:103-150. No code changes needed for multi-clinic. | 2026-06-06 |
| Redis key isolation via branch_id in key name | Already implemented. token:{doctor_id}:{branch_id}:{date} -- no cross-clinic collision possible. | 2026-05-15 (original) |
| Branch isolation via SQL WHERE clause | CLAUDE.md Rule 1. Every query includes branch_id. Legal requirement under DPDP Act. | 2026-05-15 (original) |

### Deferred decisions (not enough information yet)

| Decision | What is needed | Earliest resolution |
|---|---|---|
| Trunk split timing (1 to 2-3 trunks) | Real peak concurrency data from 10 live clinics | 30-60 days post-launch |
| Multi-region agent deployment | Evidence that latency exceeds 500ms for non-Mumbai clinics | Post-launch monitoring |
| Sarvam failover STT/TTS | Evidence of Sarvam downtime exceeding 10 min | Post-launch monitoring |
| DID pre-purchase pool size | Vobiz KYC answer (per-account vs per-DID) + onboarding velocity target | After Question 2 answered |

### Escalation items (client decision required before implementation)

| Item | Options | Impact |
|---|---|---|
| Google Calendar approach | A: shared service account, B: per-clinic OAuth | A = simpler, B = more standard. Both work. |
| Target city list for DID pre-purchase | Vinay provides 10 cities | Blocks DID inventory check with Vobiz |

---

## 12. Migration path from current state

### What is already wired (no changes needed for multi-clinic)

| Component | Status | Why it works at 10 clinics |
|---|---|---|
| _resolve_branch_from_sip() | Working (agent/agent.py:103-150) | Queries branches table by DID. Add rows = add clinics. |
| Redis token keys | Working (agent/tools/booking_tools.py) | Key includes branch_id -- isolated by design. |
| branch_guard middleware | Working (backend/middleware/branch_guard.py) | JWT branch_id claim scopes all API access. |
| audit_log with branch_id | Working (backend/services/audit_service.py) | Every audit row tagged with branch_id. |
| Rate limiting | Working (backend/middleware/rate_limit.py) | Per-IP, not per-clinic. Scales independently. |
| Security headers + CORS | Working (backend/middleware/security_headers.py) | Global, not per-clinic. |

### What is net-new for multi-clinic

| Component | Work required | Implementation plan task |
|---|---|---|
| Postgres pool tuning | Add pool_size=10, max_overflow=20 to database.py | Task 2 |
| Multi-DID provisioning script | Extend provision_vobiz_trunk.py with --add-did and --register-clinic | Task 3 |
| Onboarding service | backend/services/onboarding_service.py -- end-to-end clinic setup | Task 4 |
| Razorpay -> onboarding trigger | POST /onboarding/start webhook handler | Task 5 |
| Onboarding frontend wizard | frontend/src/pages/Onboarding.jsx + components | Task 6 |
| UptimeRobot per-DID monitoring | API integration for auto-monitor creation | Task 7 |
| Capacity monitoring job | backend/jobs/capacity_monitor.py -- daily peak check | Task 8 |
| Multi-tenant validation tests | tests/integration/test_multi_clinic_isolation.py | Task 9 |
| Self-hosted LiveKit deployment | infra/fly.livekit.toml -- Fly.io bom Mumbai | Task 10 |

---

## Appendix A: Vobiz account structure reference

```
Reseller Account: MA_WJ7ZPSWT
+-- Trunk: vachanam-trunk (shared)
|   +-- concurrent_calls_limit: 30 (target; currently 10)
|   +-- DID: +914066XXXXXX (Hyderabad - Clinic 1)
|   +-- DID: +912266XXXXXX (Mumbai - Clinic 2)
|   +-- DID: +918046XXXXXX (Bangalore - Clinic 3)
|   +-- ... (up to 10 DIDs)
+-- inbound_destination: vachanam-gimml0ao.livekit.cloud
```

## Appendix B: LiveKit SIP configuration reference

```
Inbound Trunk:
  name: vachanam-inbound
  numbers: ["+914066XXXXXX", "+912266XXXXXX", "+918046XXXXXX", ...]
  auth_username: <from Vobiz>
  auth_password: <from Vobiz>

Outbound Trunk:
  name: vachanam-outbound
  address: <Vobiz SIP domain>
  auth_username: <from Vobiz>
  auth_password: <from Vobiz>

Dispatch Rule:
  name: vachanam-dispatch
  type: individual
  agent_name: voice-assistant
  # No trunk_ids filter = catch-all for any inbound trunk
```