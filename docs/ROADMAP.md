# Vachanam — Roadmap

Current roadmap, verified **2026-08-16**. Historical phase specifications remain
under `docs/phases/`; they describe how the product was built, not the current
deployment state.

## Shipped foundation

- Multi-tenant FastAPI backend, Supabase Postgres migrations, Upstash Redis,
  JWT/Google authentication, audit/security controls, and owner/admin surfaces.
- Production LiveKit voice agent on Fly Mumbai using Soniox Japan STT/TTS,
  Gemini with fallback, deterministic booking tools, interruption handling,
  language switching, prompt caching, and per-turn latency telemetry.
- Day-specific multi-window doctor schedules, token- and slot-based doctors,
  availability alternatives, atomic booking/rescheduling/cancellation, Google
  Calendar integration, reminders, follow-ups, leave, queues, and walk-ins.
- React/Vite clinic PWA on Cloudflare with onboarding, doctors, patients,
  imports, queue, billing, analytics, settings, support, conversations, and
  custom voice management.
- Razorpay payment/webhook infrastructure, usage metering, owner cost ledger,
  manual paid activation, and the founding-clinic trial lifecycle.
- WhatsApp message/booking infrastructure, templates, outbox, reminders and
  follow-ups. Public self-serve onboarding remains gated pending Meta approval.

## Release gate now

1. Keep one Alembic head and apply it manually to production before schema-
   dependent code goes live.
2. Require Ruff, the full PostgreSQL/Redis backend suite, frontend tests/lint/
   build, and secret scan before deployment.
3. Verify Render health, Cloudflare content, and a freshly registered Fly voice
   worker after every production release.
4. Run real-call and real-payment smoke tests whenever provider credentials or
   routing change; automated tests cannot prove the PSTN or bank edge.

## Immediate commercial milestone

- Onboard the first 100 eligible clinics with the 14-day unlimited founding
  trial, no card, no auto-conversion, and an explicit post-trial purchase.
- Capture consented testimonials and measure calls answered, successful
  appointment mutations, latency, support incidents, trial cost, conversion,
  paid gross margin, and retention.
- Replace conservative cost assumptions with provider invoices and the product
  owner's per-clinic cost ledger before changing ₹1,999 + ₹6/min pricing.

## Next, only when triggered

- Turn on public WhatsApp Embedded Signup after Meta Tech Provider approval and
  complete a real clinic-number certification run.
- Add capacity or self-host components when measured concurrency—not clinic
  count alone—approaches current limits.
- Introduce tested database restore/failover and stronger observability before
  the operational blast radius justifies them.
- Revisit tiered minute pricing only after actual paid usage proves that the
  margin floor remains safe.

## Non-negotiable product rule

Prompt wording may improve the conversation, but it cannot be the only guard
for patient privacy, tenant routing, availability, appointment mutation,
billing, or trial enforcement. Those outcomes remain database- and
architecture-enforced.
