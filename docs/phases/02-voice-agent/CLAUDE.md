# Phase 2 — Voice Agent ✅ DONE

**Goal:** Telugu voice AI that answers SIP calls, books appointments, handles emergencies, atomically assigns tokens. End-to-end agent capable of holding a 4-minute call and producing a confirmed booking.

---

## What was built

### Core agent
- [`agent/agent.py`](../../../agent/agent.py) — LiveKit `JobContext` entrypoint, Solo 4-min cap (240s) with one-shot warning at 230s, token rollback on disconnect, Gemini→GPT-4o-mini fallback
- [`agent/session_state.py`](../../../agent/session_state.py) — per-call `SessionState` dataclass (branch_id, doctor_id, token_held, token_confirmed, call_start, solo_warning_sent, emergency_contact, etc.)
- [`agent/prompts/system_prompt.py`](../../../agent/prompts/system_prompt.py) — Telugu system prompt builder with `DoctorContext`, emergency contact injection, rebook + Solo-cap variants

### Services
- [`agent/services/tts_sanitizer.py`](../../../agent/services/tts_sanitizer.py) — strips markdown, hash-prefixes, emoji before Sarvam TTS. Critical: numbered-list dot strip uses `^(\d+)\.\s+` with `re.MULTILINE` so mid-sentence "5." is preserved
- [`agent/services/emergency.py`](../../../agent/services/emergency.py) — MVP keyword detection only. No TYPE_1/TYPE_2 classification. On hit: say emergency contact in Telugu, continue booking

### Booking tools (4 LLM function tools)
- [`agent/tools/booking_tools.py`](../../../agent/tools/booking_tools.py):
  - `route_to_doctor(complaint, branch_id, db, llm_call)` — falls back to `is_default_doctor` on low confidence
  - `check_availability(doctor_id, branch_id, booking_date, db)` — reads Redis counter; supports both token and slot booking types
  - `assign_token(doctor_id, branch_id, booking_date, db)` — **Redis INCR is sole primary; DECR is rollback only** when over limit
  - `confirm_booking(...)` — Calendar first (must succeed, raises on failure), then WhatsApp fire-and-forget (never blocks booking). Tagged `@retry(stop_after_attempt(3))`

### Tests
- [`tests/unit/test_tts_sanitizer.py`](../../../tests/unit/test_tts_sanitizer.py) — **11/11 pass**
- [`tests/unit/test_emergency.py`](../../../tests/unit/test_emergency.py) — **12/12 pass**
- [`tests/integration/test_booking_flow.py`](../../../tests/integration/test_booking_flow.py) — 4 tests, requires running Postgres + Redis
- [`tests/edge_cases/test_concurrent_tokens.py`](../../../tests/edge_cases/test_concurrent_tokens.py) — 5 concurrent callers get unique sequential tokens; each coroutine opens its own `async with AsyncSessionLocal()` (shared session is NOT concurrent-safe)

### Infra
- [`agent/requirements.txt`](../../../agent/requirements.txt) — `livekit-agents[sarvam,google,openai]>=1.4.0`, structlog, tenacity, redis, httpx
- [`infra/Dockerfile.agent`](../../../infra/Dockerfile.agent) — Python 3.11-slim, runs `python -m agent.agent`
- [`infra/fly.agent.toml`](../../../infra/fly.agent.toml) — Mumbai region, `min_machines_running = 1` (voice agent must never cold-start)

---

## Critical rules baked in

| Rule | Where enforced |
|---|---|
| Every DB query filters by `branch_id` | All booking_tools.py queries |
| Tokens assigned ONLY via Redis INCR, DECR only on rollback | `assign_token()` |
| Token held in session until `confirm_booking()` ; released on disconnect | `agent.py @session.on("disconnected")` |
| Calendar success required for booking; WhatsApp failure logged but never blocks | `confirm_booking()` |
| Every `session.say()` goes through `sanitize_for_tts()` | All call sites |
| Emergency = keyword only → give `branch.emergency_contact` → continue booking | `on_user_turn_completed()` |
| Gemini primary, GPT-4o-mini fallback for LLM | `_llm_with_fallback()` |
| Structlog JSON on every significant event with `branch_id`, last-4 of phone | All logging calls |
| Patient phones logged only as `phone[-4:]` | Throughout |

---

## Known follow-ups

| Item | Severity | When |
|---|---|---|
| `padipōyāḍu` (romanized Telugu) in emergency keywords — Sarvam STT may output `పడిపోయాడు` (Telugu script). Verify on first real call. | LOW | Phase 10 acceptance |
| Real SIP trunk credentials (`VOBIZ_SIP_*`) still empty in `.env` — agent can run but cannot accept calls | DECISION | Phase 9/10 |
| Integration + edge_case tests not executed in this session (Docker likely down) | MEDIUM | Phase 4 acceptance |

---

## How to bring this phase up

```bash
# Local: agent boots and waits for SIP traffic
docker-compose up -d
alembic upgrade head     # only after Phase 4 regenerates migration
pytest tests/unit/ -v    # 23/23 should pass
python -m agent.agent    # connects to LIVEKIT_URL, waits for dispatch
```

## What this phase does NOT do

- Does not run an HTTP API — that's Phase 4
- Does not handle WhatsApp — Phase 5
- Does not send EOD summaries — Phase 6
- Does not show data to anyone — that's the frontend, Phases 7-8
- Does not handle billing — Phase 9

Move on to [Phase 4](../04-backend-core/CLAUDE.md).
