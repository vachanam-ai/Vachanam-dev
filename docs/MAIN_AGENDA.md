# Vachanam — Main Agenda

Current product and operating summary. Last verified: **2026-08-16**. Detailed
implementation truth lives in `CLAUDE.md`, `docs/STATUS.md`,
`docs/ARCHITECTURE.md`, and the deployment runbooks.

## What Vachanam is

Vachanam is a multilingual clinic receptionist for phone and WhatsApp. It
answers patients in Telugu, Hindi, or English; grounds doctor and clinic answers
in the clinic database; checks day-specific availability; books, reschedules,
and cancels appointments; and keeps the clinic dashboard and Google Calendar in
sync. Database success is the authority: the assistant must never claim a
mutation succeeded before the committed record is verified.

## Who it serves

The initial customer is an Indian clinic with one or more doctors whose
receptionist cannot answer every call. Each DID, branch, patient record,
appointment, WhatsApp account, custom voice, and outbound caller ID is strictly
tenant-owned. Ambiguous or mismatched tenant identity fails closed.

## Runtime

- Vobiz routes the clinic DID through LiveKit to always-warm voice workers on
  Fly.io Mumbai.
- Soniox Japan provides production STT (`stt-rt-v5`) and TTS (`tts-rt-v1`).
  Sarvam is an emergency STT fallback only. Gemini 2.5 Flash is the primary LLM
  with GPT-4o mini fallback.
- Deterministic tools perform availability checks and appointment mutations.
  PostgreSQL constraints/transactions and Redis coordination prevent duplicate
  work; Google Calendar is updated as part of the supported schedule workflow.
- FastAPI runs on Render, the React PWA is served by Cloudflare, Supabase
  Postgres is in Mumbai, and Upstash provides Redis.
- Reminder and follow-up jobs use each branch's configured channel and outbound
  identity. Missing or conflicting trunk/WhatsApp ownership blocks delivery
  instead of borrowing another clinic's identity.

## Commercial model

- **Voice:** ₹1,999/month plus ₹6 per billable voice minute.
- **WhatsApp add-on:** ₹1,499/month. **WhatsApp only:** ₹1,999/month.
- **Founding offer:** the first 100 eligible clinics receive 14 calendar days
  of unlimited voice usage, without a card or automatic conversion. Service
  pauses at exact expiry and paid billing begins only after explicit activation.
- Current conservative cost model is ₹2.90 per voice minute plus ₹1,499 monthly
  fixed branch allocation. See `docs/PRICING_MODEL_2026-08-16.md` for the full
  margin and trial-exposure model.

## Current priority

The product is in production hardening and first-clinic onboarding. The release
gate is: one Alembic head, Ruff clean, the full backend suite green on PostgreSQL
and Redis, frontend tests/lint/build green, secret scan green, production schema
migrated, Render/Cloudflare healthy, and a freshly registered Fly voice worker.
No prompt-only behavior is treated as a correctness guarantee for booking,
rescheduling, cancellation, tenant isolation, billing, or trial enforcement.

## Operating constraints

- Render's free-plan blueprint does **not** run migrations. Apply
  `alembic upgrade head` manually for every migration-bearing release.
- Never commit `.env`, provider credentials, service-account JSON, recordings,
  or patient data.
- WhatsApp self-serve onboarding remains marked coming soon until Meta Tech
  Provider approval; already connected test numbers may continue to operate.
- Custom voice is limited to one clinic-owned voice and is available only while
  the provider capacity reserved for the founding offer remains available.
