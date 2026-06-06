# Vachanam — Pipecat + Vobiz Integration Design

**Date:** 2026-06-07
**Author:** Vinay Rongala (client) + orchestrator
**Status:** Approved (4 open items resolved by client 2026-06-07) — ready for plan
**Replaces:** LiveKit Agents 1.5.9 + Vobiz SIP trunk integration (removed in commit `f3c79ca`)
**Goal:** First real inbound Telugu call answered by Pipecat-based voice agent through Vobiz WebSocket transport (no SIP), within 4-6 hours of dispatch.
**Sits inside:** Phase 1 (voice agent core).

---

## 1. Why this spec exists

Phase 4.5 closed 2026-06-05. Phase 1 (voice agent) restart was blocked from 2026-06-06 to 2026-06-07 by Vobiz SIP routing failures despite verbatim configuration matching the official Vobiz + LiveKit integration guide. Root cause confirmed: Vobiz back-office gates (`is_verified=false`, DID `provider=""`, `usage_status=""`) — out of our control.

Decision (2026-06-07): pivot the voice stack from **LiveKit Agents over SIP** to **Pipecat over Vobiz WebSocket**. This bypasses the entire SIP path that broke. Vobiz still controls the PSTN side, but the Vobiz-Vachanam contract is now an HTTP webhook + a WebSocket — no SIP trunk, no LiveKit Cloud.

Pipecat was independently evaluated and picked on technical merit (see brainstormer report 2026-06-07, summarized in [[project-vachanam-status]] line 52):
- 8M-parameter Smart Turn v3 vs LiveKit's 500M Qwen2.5 → 10-100× faster barge-in inference on telephony VMs
- Published 94.7% English barge-in accuracy + per-language false-positive/missed-interrupt numbers (LiveKit publishes only "39% relative improvement")
- Telephony serializer (`pipecat-ai-vobiz`) is first-party and actively maintained — handles L16 + multi-rate + start/stop event lifecycle

LiveKit Cloud is now fully wound down (all trunks + dispatch deleted yesterday). Self-hosted LiveKit on Fly.io Mumbai is also off the table — Pipecat replaces both.

## 2. Goals and non-goals

### Goals
- One FastAPI server (`agent/server.py`) handles all Vobiz webhooks + WebSocket upgrades
- One Pipecat pipeline (`agent/bot.py`) runs per active call (asyncio task)
- Telugu STT (Sarvam Saaras v3, `te-IN`) + Gemini 2.5 Flash + Sarvam Bulbul v3 TTS — same vendor stack as Phase 2 design
- Gemini → GPT-4o-mini fallback (CLAUDE.md RULE 9)
- 4 booking tools (`route_to_doctor`, `check_availability`, `assign_token`, `confirm_booking`) wired via Pipecat `FunctionSchema` + `llm.register_function()`
- Emergency keyword detect → return `<Dial>{branch.emergency_contact}</Dial>` to transfer the live PSTN call (overrides CLAUDE.md RULE 7 per [[feedback-emergency-transfer]])
- TTS sanitize on every spoken string (CLAUDE.md RULE 6) via Pipecat output filter
- Branch resolution from the dialed DID (CLAUDE.md RULE 5) — `to` query parameter on the WebSocket URL → SQL `Branch` lookup
- DPDP Step 0 disclosure spoken before any LLM turn — wired in the system prompt + `bot.say()` first message
- Recording enabled for testing (TESTING-ONLY override 2026-06-07 — see §6)
- Multi-tenant: one FastAPI process, N concurrent Pipecat pipelines, hard cap = VM RAM (~10-15 per 1GB Fly.io VM)

### Non-goals (deferred)
- WhatsApp confirmation send — MVP2 deferred. `MetaService` stays a no-op stub, called fire-and-forget by `confirm_booking`.
- Real Google Calendar integration — Phase 4 onboarding. `CalendarService` stub returns `stub-{uuid4}` event ID. Must succeed (no exception) per CLAUDE.md RULE 4.
- Solo 4-min cap enforcement — billing-tier feature, not needed for testing. Env flag `MAX_CALL_DURATION_SECONDS` (default `0` = unlimited). Re-enable at Phase 4 onboarding when first Solo clinic activates. Tracked as new TD entry.
- Outbound calls (`/start` endpoint) — built but not exercised yet. Inbound-first.
- Production deployment to Fly.io — Phase 5. Dev runs locally + Cloudflare Tunnel.

## 3. Architecture

```
Caller dials DID +918046733493
  │
  ▼
Vobiz PSTN ──POST /answer──▶  FastAPI uvicorn :7860 (agent/server.py)
  │                              │
  │           ◀──XML─────────────┘  returns <Speak> + <Stream> + <Record>
  │                                  Stream URL = wss://agent-dev.vachanam.in/ws
  │                                                  ?call_id=X&to=DID&from=CALLER
  │
  └──Bidirectional WebSocket μ-law 8kHz──▶  /ws endpoint
                                            │
                                            ▼
                          One Pipecat PipelineTask per call
                          (agent/bot.py:run_pipeline)
                          ─────────────────────────────────
                          transport (Vobiz frame serializer)
                              ↓
                          STT (SarvamSTTService, saaras:v3, te-IN)
                              ↓
                          User context aggregator (Silero VAD wired here per Pipecat 1.x)
                              ↓
                          Emergency interceptor (frame processor)
                              ↓ (if emergency keyword: stop pipeline + flag for transfer)
                          LLM (GoogleLLMService Gemini 2.5 Flash → OpenAI GPT-4o-mini fallback)
                              ↓
                          TTS sanitizer (output frame filter)
                              ↓
                          TTS (SarvamTTSService, bulbul:v3, Telugu voice)
                              ↓
                          transport (back to Vobiz over WebSocket)
```

Cloudflare Tunnel `vachanam-agent` exposes `:7860` at `https://agent-dev.vachanam.in` (named tunnel, stable URL across restarts).

## 4. File map

### KEEP unchanged (cleaned in earlier commits)
- `agent/__init__.py`
- `agent/logging_config.py`
- `agent/session_state.py`
- `agent/prompts/system_prompt.py` — needs Step 0 update to include recording disclosure (see §6)
- `agent/services/tts_sanitizer.py`
- `agent/services/emergency.py`
- `agent/tools/booking_tools.py` — 4 async fns. Already stripped of `@function_tool` decorators (commit `f3c79ca`).

### CREATE
- `agent/server.py` — FastAPI app. Endpoints:
  - `POST /answer` — returns the `<Response>` XML with `<Speak>` greeting + `<Stream>` WebSocket URL + `<Record>` (gated by `RECORDING_ENABLED`).
  - `WS /ws` — accept WebSocket, parse Vobiz start event for call metadata, hand off to `agent/bot.py:run_pipeline`.
  - `POST /start` — outbound trigger (built but not exercised in this sprint).
  - `POST /recording-finished` — Vobiz callback when recording completes (gated by `RECORDING_ENABLED`).
  - `POST /recording-ready` — Vobiz callback with MP3 download URL (gated by `RECORDING_ENABLED`). Downloads to `agent/recordings/`. Gitignored.
  - `POST /transfer-emergency/{call_id}` — internal endpoint bot.py calls to switch the live call to `<Dial>{branch.emergency_contact}</Dial>`. Implementation note: Vobiz `<Redirect>` verb or end-of-call answer-replacement TBD; voice-agent-engineer confirms in TDD.
  - `GET /health` — liveness probe.
- `agent/bot.py` — Pipecat pipeline. One function `run_pipeline(websocket, call_id, branch_id, did, caller)`:
  1. Parse Vobiz start event via `pipecat-ai-vobiz` helper (`parse_vobiz_start(runner_args.websocket)`).
  2. Build `SessionState` with `branch_id` resolved from `did`, `call_start=now`, `session_id=call_id`.
  3. Load branch + active doctors from DB in parallel with greeting (Phase 2 latency carryover).
  4. Construct `WebsocketServerTransport` with `add_wav_header=False` + Vobiz frame serializer + 8kHz input/24kHz internal/8kHz output resample.
  5. Construct `SarvamSTTService(saaras:v3, te-IN)`, `GoogleLLMService(gemini-2.5-flash)` wrapped in fallback adapter, `SarvamTTSService(bulbul:v3)`.
  6. Register the 4 booking tools via `FunctionSchema` + `llm.register_function()`. Each handler receives `FunctionCallParams`, calls `result_callback({...})`.
  7. Wire LLM context aggregator with `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(...))` — Pipecat 1.x requires VAD on the aggregator, NOT the transport.
  8. Wire emergency interceptor frame processor — listens for `TranscriptionFrame`, calls `emergency.detect()`, on hit pushes a `BotStoppedSpeakingFrame` + signals the server task to `<Redirect>` the live call to the transfer endpoint.
  9. Wire TTS sanitizer as a frame processor between LLM and TTS — every `TextFrame` content goes through `sanitize_for_tts()` before reaching the TTS engine.
  10. Start `PipelineRunner().run(PipelineTask(pipeline))`. On disconnect, release any unconfirmed token via Redis DECR (CLAUDE.md RULE 3).
- `agent/services/calendar_stub.py` — minimal `CalendarService` with `async def create_booking_event(...) -> str` returning `f"stub-{uuid4()}"` + structlog warning. PII-redacted log (phone last-4 only).
- `agent/services/meta_stub.py` — minimal `MetaService` with `async def send_booking_confirmation(...) -> None` that logs a warning and returns. WhatsApp MVP2.
- `agent/recordings/.gitkeep` — folder placeholder; `agent/recordings/*.mp3` gitignored.
- `agent/requirements.txt` — listed in §5.

### MODIFY
- `.env.example` — DELETE `LIVEKIT_*`, `VOBIZ_SIP_*`, `VOBIZ_TRUNK_ID`. RENAME `VOBIZ_PARTNER_AUTH_ID` → `VOBIZ_AUTH_ID`, `VOBIZ_PARTNER_AUTH_TOKEN` → `VOBIZ_AUTH_TOKEN`. ADD `PUBLIC_URL`, `RECORDING_ENABLED`, `MAX_CALL_DURATION_SECONDS`.
- `.env` — same changes (preserve existing values where keys are renamed; Vinay sets new keys).
- `backend/config.py` — same env-field changes.
- `infra/Dockerfile.agent` — base `python:3.12-slim`, install Pipecat 1.x extras, expose 7860, CMD `uvicorn agent.server:app --host 0.0.0.0 --port 7860`.
- `agent/prompts/system_prompt.py` — Step 0 disclosure adds recording-consent sentence in Telugu when `RECORDING_ENABLED=true`.
- `.gitignore` — append `agent/recordings/*.mp3` and `agent/recordings/*.wav`.

### DELETE
None — old LiveKit code already removed.

## 5. Dependency stack

```
# agent/requirements.txt
pipecat-ai[websocket,silero,openai,google,sarvam]>=1.2.0,<2
pipecat-ai-vobiz>=0.0.3,<0.1
fastapi>=0.110
uvicorn[standard]>=0.27
aiohttp>=3.9
python-dotenv>=1.0
loguru>=0.7
python-multipart>=0.0.6
structlog>=24.1
tenacity>=8.2
redis>=5.0
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
```

Pipecat 1.x requirement (per Vobiz-X-Pipecat README): "VAD must be wired on `LLMUserAggregatorParams`, NOT transport params". Carry this constraint into bot.py.

## 6. Recording — TESTING-ONLY override

**Production rule (still target):** No voice recording. Live audio streams through Sarvam STT/TTS and is discarded. Only booking actions persist via `audit_log`.

**Testing exception (2026-06-07 → first paying clinic):** Recording temporarily enabled to evaluate audio quality, barge-in accuracy, Telugu STT fidelity in real calls. Memory entry [[feedback-no-voice-recording]] updated to reflect this exception.

Implementation:
- Env flag `RECORDING_ENABLED=true` in dev `.env`.
- When flag is on, `/answer` XML includes:
  ```xml
  <Record action="https://{PUBLIC_URL}/recording-finished" recordSession="true" maxLength="3600" fileFormat="mp3"/>
  ```
- Recordings download to `agent/recordings/` only. Never in DB. Never sent to clinic/patient. Never persisted past 30 days (cleanup script TBD when needed).
- System prompt Step 0 in Telugu MUST add: "ఈ కాల్ నాణ్యత మెరుగుదల కోసం రికార్డ్ చేయబడుతుంది." ("This call is recorded for quality improvement.")
- Privacy Policy + ToS + DPA say "no voice recording" — creates a doc/code mismatch for the duration of this override. Tracked as new TD entry: resolve before first paying clinic by either reverting the override or rewriting policy.
- Production XML omits `<Record>` entirely when `RECORDING_ENABLED=false`.

## 7. Multi-tenant scale model

- **One FastAPI process** accepts all `/answer` + `/ws` upgrades.
- **One Pipecat `PipelineTask` per active call** as an asyncio task on the same event loop.
- Branch resolution per `/ws` connection via `to` query parameter → SQL lookup → cached in `SessionState`.
- All per-call state lives in `SessionState` (no module-level mutables in agent code).
- Concurrency cap = VM RAM. Pipecat pipeline ~50-100 MB per call. 1 GB VM → 10-15 concurrent. Scale by adding VMs.
- Redis INCR token assignment unchanged → atomic across all VMs and processes.
- Fly.io autoscale at Phase 5 (`--max-per-region` keyed on average concurrent calls).
- 100+ clinics × 5-10 calls each = 500-1000 concurrent design target. ~40-80 1GB VMs = ₹33k-66k/month VM cost at Fly.io list price. Acceptable per-clinic unit economics (Plan 2 Clinic = ₹7,999/clinic; gross margin holds).

## 8. Cloudflare Tunnel — public URL for Vobiz webhooks

- Named tunnel `vachanam-agent` → hostname `agent-dev.vachanam.in`.
- One-time setup: `cloudflared tunnel login` → `cloudflared tunnel create vachanam-agent` → `cloudflared tunnel route dns vachanam-agent agent-dev.vachanam.in`.
- Run alongside uvicorn: `cloudflared tunnel run vachanam-agent --url http://localhost:7860`.
- `PUBLIC_URL=https://agent-dev.vachanam.in` in `.env`.
- Vobiz Console Application "vachanam-dev" Answer URL = `https://agent-dev.vachanam.in/answer`.
- Phase 5: drop Cloudflare Tunnel, point Vobiz directly at the Fly.io public hostname. Same `PUBLIC_URL` env field, different value.

## 9. Open items resolved by client (2026-06-07)

| # | Question | Resolution |
|---|---|---|
| 1 | Public URL — Cloudflare Tunnel or ngrok? | **Cloudflare** (free, stable, named tunnel) |
| 2 | Vobiz Application name | `vachanam-dev` |
| 3 | Solo 4-min cap enforcement now? | **No.** Billing-tier feature. Env flag added, default unlimited. Re-enable at Phase 4 onboarding. TD entry. |
| 4 | Recording ON or OFF for testing? | **ON** (testing-only override, see §6). Memory updated. TD entry for policy/code mismatch. |

## 10. Testing strategy (Vinay: "extreme perfection and extreme testing")

Per CLAUDE.md QUALITY_BAR + subagent-driven-development skill:
- **Per-task TDD:** write failing test → minimal impl → green → commit. Bite-sized tasks defined in plan doc.
- **Per-task two-stage review:** spec-compliance reviewer first (matches the plan), then code-quality reviewer (CLAUDE.md 10 rules, structlog, type hints, no bare except, etc.).
- **Test coverage layers:**
  - Unit: emergency keyword detection, TTS sanitizer (existing tests stay green), config env-var rename
  - Integration: FastAPI `/answer` returns valid XML for both recording-on and recording-off; `/ws` rejects connections without `to` param; emergency-transfer endpoint returns `<Dial>` XML
  - Edge: WebSocket disconnect mid-booking releases token via Redis DECR; concurrent callers to same doctor get distinct token numbers (existing test `test_concurrent_tokens.py`)
  - Smoke: one full call placed through the dev DID, transcript reviewed manually, recording played back
- **Manual gate (Vinay):** first real call review — Telugu quality, barge-in feel, latency perception. No production traffic until Vinay signs off audibly.

## 11. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Pipecat 1.x API drift breaks bot.py | Pin `>=1.2.0,<2` in requirements; CI test runs against the pin; upgrade is a separate sprint |
| Sarvam WebSocket STT dies on long silence (Pipecat issue #3699) | Wire `keepalive_interval=5.0` + `keepalive_timeout` on `SarvamSTTService` from day one; auto-reconnect handler in bot.py |
| Vobiz `<Dial>` mid-call transfer semantics — does it answer-replace or 302-redirect? | TDD task validates with one test call before integrating into emergency flow |
| Cloudflare Tunnel disconnects = Vobiz fails to reach `/answer` | Cloudflare Tunnel is highly reliable; if it flaps, monitor + restart. Phase 5 swaps to Fly.io public hostname |
| Recording grows unbounded | Local folder, manual cleanup until first paying clinic; TD entry tracks retention-policy work |
| Per-call asyncio task leaks if pipeline crashes | Wrap `PipelineRunner().run()` in `try/finally` that always closes the WebSocket and releases Redis tokens |

## 12. Acceptance criteria

1. `pytest tests/` — all existing tests still pass, plus new tests for `/answer` XML and emergency-transfer endpoint
2. `uvicorn agent.server:app --port 7860` starts cleanly with no exceptions
3. `cloudflared tunnel run vachanam-agent` reaches `agent-dev.vachanam.in` and proxies to local :7860
4. `curl -X POST https://agent-dev.vachanam.in/answer` returns the expected XML
5. Vobiz Console "vachanam-dev" Application configured with the answer URL and DID `+918046733493` assigned
6. One real inbound call from Vinay's phone to `+918046733493` is answered by the Pipecat agent in Telugu, includes the recording-consent disclosure, accepts a fake booking, ends cleanly
7. Recording MP3 saved under `agent/recordings/` and playable
8. `audit_log` has a `booking.confirmed` row from the test call
9. Vinay's audible sign-off on quality + decision: keep recording or revert override

---

**Next step:** implementation plan at `docs/superpowers/plans/2026-06-07-pipecat-vobiz-integration.md` with bite-sized TDD tasks. Execution via superpowers:subagent-driven-development.

Links: [[project-vachanam-status]] [[feedback-no-voice-recording]] [[feedback-emergency-transfer]] [[project-vobiz-kyc-blocker]]
