# Phase 11 — Reliability Hardening 🅿️ DEFERRED (placeholder)

**Status:** Deferred. Do NOT pre-build any item in this phase. Each item is real engineering work justified by real signals from production, not aspirational platform building.

**Posture target:** Move from MVP-launch (~99.4% uptime, single Mumbai region, manual failover) toward Scale-ready (~99.9% uptime, automated failover, on-call rotation).

---

## When to start this phase

ANY of these three triggers fires:

1. **Volume trigger:** sustained real call volume > 100/day across all clinics. Auto-rollback and metrics infra start paying for themselves.
2. **Outage trigger:** first major outage (> 30 min user-impacting downtime). Post-mortem identifies a class of failure that single-region cannot survive.
3. **Customer trigger:** an enterprise / chain customer asks for SOC2 readiness or 99.9% SLA in writing.

Until then: keep MVP-launch posture from `docs/superpowers/specs/2026-05-22-security-hardening-design.md`. Don't gold-plate.

---

## What this phase WILL eventually deliver (deferred backlog)

| Item | Why it's deferred | Trigger to build |
|---|---|---|
| Multi-region active-passive (Mumbai → Singapore standby with < 60s failover) | Cost: ~₹3,000/mo. Until you have a Mumbai outage that hurts a real clinic, no business case. | Outage trigger or 50+ clinics |
| Multi-region active-active (load split, sub-region routing) | Cost: ~₹15,000/mo + 2-week eng. Only meaningful at 100+ clinics. | Customer trigger or 100+ clinics |
| Blue-green deploys with traffic shifting | Render + Fly basic deploys are good enough. Blue-green matters when "broken deploy" = "lost customer". | Outage trigger |
| Automated rollback on metric regression | Needs metrics pipeline (Datadog ₹15k+/mo) + feature flags (LaunchDarkly ₹10k+/mo) + a baseline of normal. | Volume trigger |
| On-call rotation + PagerDuty | Currently you're solo on-call. PagerDuty starts when you have a second person. | Hire / second engineer |
| Chaos engineering monthly drill (kill a Fly machine, see what happens) | Without auto-failover infra, chaos = real outage. | After multi-region |
| Datadog / Sentry APM | Render + Fly logs + UptimeRobot cover the MVP. Datadog is ₹15k+/mo. | Volume trigger |
| A/B testing infra (statsig / launchdarkly / homegrown) | Below 100 clinics, no statistically significant signal possible. | Volume trigger + product team |
| Status page automation | Manually post to a status page is fine at 5 clinics. | Customer trigger |
| Auto-merged Dependabot for non-prod-affecting deps | Auto-merge breaks prod in 2-3% of cases. Until CI is rock-solid, manual review is cheaper than the outage. | Strong CI track record over 6 months |
| 24/7 SOC2 audit pipeline | Six-figure auditor cost. Only for enterprise customers. | Customer trigger |
| Distributed tracing (OpenTelemetry collector + Jaeger / Tempo) | Single-instance Render = single trace surface. Tracing matters for multi-service. | After multi-region or microservice split |
| Disaster recovery drill quarterly (full restore from backup into clean account) | We do simpler backup verification in Phase 10. Full DR is enterprise-grade. | Customer trigger |

---

## What we ALREADY do for reliability (MVP-launch posture, in Phases 4.5 + 10)

These are NOT deferred. They ship in their planned phases:

- LLM fallback (Gemini → GPT-4o-mini) via `FallbackAdapter` — shipped 2026-05-29
- External call retry: `@retry(stop_after_attempt(3), wait=wait_exponential(...))` on Sarvam, Meta, Calendar, Razorpay
- Graceful degradation: Calendar required; WhatsApp fire-and-forget (never fails booking)
- Auto-restart on crash: Fly + Render handle this natively
- Health-check gating on deploys: `/health` must return 200 or rollout fails
- HTTPS + HSTS + TLS 1.2+ via Cloudflare edge
- DDoS protection via Cloudflare free tier
- Daily Neon backup with 7-day retention
- 2-min UptimeRobot pings → SMS to ADMIN_PHONE
- Structlog JSON to Render + Fly log streams
- Dependabot weekly PRs for security patches (manual review + merge)
- CI test gate on every PR (`pytest tests/` must be green)
- Secret-in-repo CI scan
- Manual failover runbook to Singapore Render region (Phase 10 doc)
- Quarterly backup-restore drill (Phase 10 owner action)
- Quarterly self-audit (review audit_log, dependency CVEs, third-party processor list)

**Target uptime: ~99.4%** (about 4 hours/month worst case). All mitigations combined. Acceptable for MVP serving 5-20 clinics.

---

## Why NOT pre-build this phase

Per `brainstormer` and `manager.md`:

1. **YAGNI** — engineering for hypothetical scale wastes today's budget on tomorrow's problem you may never have.
2. **Wrong baseline** — reliability infra built before you have real traffic optimizes for the wrong failure modes. Real outages will surprise you; build the fix for actual failure, not imagined failure.
3. **Cost compounds** — ₹15-50k/mo recurring services drain runway before first paying clinic. That money is better spent on sales, customer support, or actual product.
4. **Complexity tax** — every reliability layer adds operational surface. More moving parts = more things that break. MVP teams collapse under complexity they thought would protect them.

If a specialist proposes building any Phase 11 item early, `manager` escalates to client. Default answer: no.

---

## What this phase does NOT include (out of scope even when triggered)

- Building a competitor to LiveKit, Sarvam, or any other vendor we depend on
- Custom orchestration that replicates Kubernetes / Fly / Render functionality
- Microservice split (single FastAPI app is right until 50k+ requests/sec)
- Custom message queue / event-sourcing rewrite

If we need those, we acquire/hire/buy. We do not build platform-level infra in this project.

---

## Acceptance criteria (when phase is triggered)

To be defined when one of the three triggers fires. Until then, this section reads:

```
[ ] [trigger fired] — [date] — [which trigger]
[ ] post-mortem written if outage trigger
[ ] specific reliability gap identified (one, not many)
[ ] cost estimate produced and approved by client
[ ] brainstormer dispatched for option analysis
[ ] one item from deferred backlog above selected for build
[ ] one item built. measure result. stop. repeat only if new trigger fires.
```

We add ONE item at a time. We do not bundle. Every item bought adds operational cost we must justify.

---

## How to recognize you're slipping into Phase 11 too early

| Smell | Reality check |
|---|---|
| "We need Datadog before launch" | UptimeRobot + Render logs work fine for 0-50 clinics |
| "We should auto-rollback bad deploys" | Render + Fly already gate on `/health`; that catches the obvious failures |
| "We need multi-region for HA" | Mumbai region alone is 99.0-99.5% per Fly's SLA. Acceptable for MVP. |
| "We need feature flags for safe rollouts" | Small team + small user base = ship and watch. Flags are for 10+ engineers. |
| "We need chaos engineering" | Real customers create chaos for free. Save the budget for after launch. |

If you find yourself wanting to build Phase 11 work before any trigger fires, dispatch `brainstormer`. Brainstormer will surface the "is this needed?" question. Manager will escalate. Client will say no. That's the protocol working.
