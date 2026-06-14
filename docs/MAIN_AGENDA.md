# Vachanam — Main Agenda

One-page project highlight. Plain English. Facts sourced from `CLAUDE.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/PROJECT_STRUCTURE.md`, and the graphify AST analysis (2026-06-03).

---

## What Vachanam Is

Vachanam is an AI-powered telephone appointment booking service for Indian clinics. A patient calls the clinic's existing phone number; the call is forwarded to a Vachanam AI agent that answers in Telugu, Hindi, or English; understands the health complaint; routes to the correct doctor; checks availability; assigns an atomic token number; confirms by voice; creates a Google Calendar event; and sends WhatsApp confirmation to both patient and doctor — all within four minutes and without any human receptionist involvement.

---

## Who It Serves

Primary: clinic owners and their receptionists across India — specifically small-to-mid-sized clinics with one to six doctors receiving 20–80 inbound patient calls per day. Secondary: the patients themselves, who get instant confirmation and a WhatsApp reminder instead of a busy signal. Vinay Rongala (founder) sells directly to clinic owners; the receptionist and doctors use the system through WhatsApp commands and a mobile PWA without needing any training.

---

## Why It Exists

A typical Indian clinic misses 20–30% of inbound calls when the receptionist is busy. Each missed call is a lost consultation worth ₹300–500. At 10 missed calls per day that is ₹3,000–5,000 of lost revenue daily — recurring, invisible, and fixable. Existing scheduling software requires patients to use an app or website; Indian patients call. Vachanam meets patients where they are (a phone call), speaks their language (Telugu), and requires zero behavior change from either the patient or the doctor.

---

## How It Works at Runtime

- A patient dials the clinic's forwarded number. Vobiz SIP trunk routes the call to a LiveKit voice agent running on Fly.io Mumbai.
- The AI greets the patient using a pre-cached Telugu WAV (sub-200ms). Sarvam Saaras v3 transcribes speech; Gemini 2.5 Flash (fallback: GPT-4o mini) drives conversation; Sarvam Bulbul v3 synthesizes replies.
- The agent detects the health complaint, routes to a doctor via the `route_to_doctor` tool, checks availability via `check_availability`, then atomically assigns a token number using `Redis INCR` (no double-booking ever — Rule 2).
- On patient verbal confirmation, the agent calls the backend's `/queue` API: a Google Calendar event is created first (failure = booking failure), then WhatsApp messages are dispatched to patient and doctor (failure = retry, booking still succeeds — Rule 4).
- The doctor manages their day entirely via WhatsApp commands (`CANCEL TODAY`, `BLOCK 2PM`, etc.). The receptionist marks attended/no-show on a mobile PWA. The clinic owner views analytics on a dashboard. APScheduler jobs send 30-minute pre-appointment reminders and an EOD summary.

---

## Tech Stack at a Glance

| Layer | Tool | Why |
|---|---|---|
| Speech-to-text | Sarvam Saaras v3 | Only viable Telugu STT; 99.99% uptime |
| Text-to-speech | Sarvam Bulbul v3 | Only natural Telugu TTS |
| Primary LLM | Gemini 2.5 Flash | Best Telugu reasoning; generous free tier |
| Fallback LLM | GPT-4o mini | Auto-activates if Gemini fails |
| Voice pipeline | LiveKit Agents 1.5.9 | Self-hosted; SIP + WebSocket; open source |
| Telephony | Vobiz | Indian DID; ₹0.65/min streaming |
| Token locking | Upstash Redis 7 | Atomic INCR; no double-booking |
| Calendar | Google Calendar API v3 | Doctors already use it; free |
| Messaging | Meta Cloud API (WhatsApp) | No BSP fee; direct; ₹0.115/message |
| Database | Neon Postgres | Serverless; pooler URL; $5/month |
| Backend | FastAPI + SQLAlchemy 2.x async | Async Python; Pydantic types |
| Voice agent host | Fly.io bom (Mumbai) | Only India-region PaaS; always-on |
| API host | Render (Singapore) | Reliable HTTP; $7/month |
| Frontend host | Cloudflare Pages | Free; global CDN |
| Payments | Razorpay | India standard; UPI + cards |

---

## Current State

Phases 1–4 complete (Foundation, Voice Agent, Razorpay Checkout, Backend Core). The backend boots (`uvicorn`), `/health` returns 200, JWT auth and queue API are live with 77/77 tests passing. Phase 4.5 (Security & Compliance) is the active phase: `fastapi-limiter` middleware is the outstanding task (13 RED tests authored as the spec). WhatsApp, Calendar jobs, receptionist PWA, dashboards, subscriptions, and deployment remain as future phases.

---

## What Graphify Revealed

Graphify version 0.8.30 was run in AST-only mode (code files; no LLM semantic pass) on 2026-06-03. Results: 46 code files, 402 nodes, 1006 edges.

- **`agent/agent.py` (now `agent/bot.py` after the Pipecat rewrite — same coupling) directly imports `backend/config.py`, `backend/database.py`, and `backend/models/schema.py`.** The voice agent (Fly.io Mumbai) and the backend API (Render Singapore) are two separate deployment containers but share Python modules via monorepo `PYTHONPATH`. A schema change in `backend/models/schema.py` requires both containers to redeploy simultaneously — this is an undocumented operational constraint not visible from reading either Dockerfile alone.

- **`Doctor`, `Patient`, `Token` schema models appear on both the agent side (8 edges each) and the backend side (8 edges each).** The SQLAlchemy ORM models are the only inter-service contract. There is no separate interface layer (no protobuf, no shared Pydantic schemas, no OpenAPI client). This is the largest single architectural coupling in the codebase.

- **`SilenceState` (degree 41) is the highest-connected node in the codebase — outranking `agent.py` (degree 40).** The silence state machine (`agent/services/silence_handler.py`) has more dependents than the agent entrypoint itself, making it the highest-impact change surface in the voice path.

- **`booking_tools.py` has 23 connections but no isolated unit test file imports it directly.** The 4 booking tool functions are only exercised through `tests/integration/test_booking_flow.py`. If a tool function's behaviour changes, the only signal is a full integration test failure — no fast-feedback unit test exists.

- **`test_rate_limit.py` ranks 8th in degree (25) despite all 13 tests being intentionally RED.** The tests already reference `config.py` and `jose` — the implementation wire-points are pre-mapped. This confirms Phase 4.5 Task 5 can land without structural refactoring; it is purely an additive implementation task.

Full graph data: `docs/_artifacts/graphify-output/ast-graph.json`
Full graph report: `docs/_artifacts/graphify-output/GRAPH_REPORT.md`
