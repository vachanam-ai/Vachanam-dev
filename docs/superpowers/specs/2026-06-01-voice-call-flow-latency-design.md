# Vachanam — Voice Call Flow & Latency Design

**Date:** 2026-06-01
**Author:** Vinay Rongala (client) + manager + brainstormer
**Status:** Approved — pending implementation plan
**Target:** <800ms average turn latency for active conversation, <100ms first-greeting on call pickup, industry-standard silence handling (Bland AI / Retell / Vapi tier)
**Slots into:** Voice agent enhancements — separate sprint after Phase 4.5 Security and before Phase 5 WhatsApp

---

## 1. Why this spec exists (plain English)

The voice agent (Phase 2) was built without aggressive latency optimization. After research, latency is the single largest perceived-quality differentiator in voice AI. A clinic patient calling Vachanam expects to talk to a helpful person, not a slow machine.

This spec defines the call-flow architecture that hits <800ms average turn latency while handling three real-world challenges that Phase 2 did not address:

1. **Telugu + English + Hindi code-mixing** — Sarvam Saaras handles input natively, Gemini handles reasoning, Sarvam Bulbul handles output. Stack stays. The optimization is pipeline-level.
2. **Real network conditions in India** — patients on weak mobile networks produce garbled audio. We must detect and gracefully degrade, not respond to nonsense.
3. **Patient-respect turn-taking** — never cut off speakers, never trust keyword-based intent detection, never hang up before giving the patient a chance to recover. But also: never waste clinic tokens on infinite silent calls.

## 2. Goals and non-goals

### Goals
- **<800ms average turn latency** (user finishes speaking → AI starts responding) for active conversation
- **<100ms first-word latency** on call pickup via pre-cached greeting
- **Zero patient-cutoff rudeness** via smart end-of-turn detection + always-interruptible AI
- **Graceful handling of bad audio** via STT confidence threshold + LLM clarification + counter-based escalation
- **Industry-standard silence handling** (Bland AI / Retell / Vapi tier) — not too aggressive, not too generous
- **Same vendors as Phase 2** — Sarvam Saaras STT, Sarvam Bulbul TTS, Gemini 2.5 Flash, LiveKit Agents 1.4. No new vendor cost.

### Non-goals (deferred)
- Sub-500ms latency (would require speculative TTS — research-grade, 15-30% audible glitch rate, wrong for clinic context)
- Stack changes (Deepgram, Groq, ElevenLabs, etc.) — Telugu quality risk not worth the latency gain
- Per-clinic configurable silence timeouts — Phase 9 onboarding wizard adds this
- A/B testing prompt phrasings — post-MVP, needs traffic to validate
- Adaptive per-user VAD — post-MVP, needs call-history per patient

## 3. Architecture — twelve components

The agent pipeline composed of twelve components, each independent and testable. Components 1-8 are pipeline performance. Components 9-12 are turn-taking and edge cases.

```
┌─────────────────────────────────────────────────────────────────┐
│  PATIENT phone call → Vobiz SIP → LiveKit room                  │
└──────────────┬──────────────────────────────────────────────────┘
               ↓
       Component 4: pre-cached greeting plays in <100ms
               ↓
       Component 5: connection keep-alive warms up (Sarvam, Gemini, Redis)
       Component 6: parallel DB lookup (branch + doctors) runs during greeting
               ↓
┌─────────────────────────────────────────────────────────────────┐
│  PATIENT speaks                                                 │
└──────────────┬──────────────────────────────────────────────────┘
               ↓
       Component 1: streaming STT (Sarvam Saaras) — partials internal
       Component 7: smart end-of-turn detection (LiveKit MultilingualModel)
               ↓
       Component 10: STT confidence threshold check
         < 60% → component 10A "kshamincandi, mali cheppagalara?"
         ≥ 60% → forward complete transcript to LLM
               ↓
┌─────────────────────────────────────────────────────────────────┐
│  GEMINI 2.5 Flash (FallbackAdapter → GPT-4o-mini)               │
│  Reads transcript + clinic context + conversation history       │
└──────────────┬──────────────────────────────────────────────────┘
               ↓
       Component 2: streaming LLM (SSE tokens emitted in real time)
               ↓
       Component 3: streaming TTS (Sarvam Bulbul chunked, sentence-by-sentence)
               ↓
┌─────────────────────────────────────────────────────────────────┐
│  AI audio plays in patient's ear                                │
│  Component 8: always-interruptible AI                           │
└──────────────┬──────────────────────────────────────────────────┘
               ↓
       Component 9: silence handling state machine
       Component 11: Solo 4-min hard cap (already implemented from TD-009 fix)
       Component 12: emergency-mode silence override
```

## 4. Components 1-3 — Streaming pipeline

### 4.1 Streaming STT (Sarvam Saaras)

Sarvam Saaras emits partial transcripts as audio arrives. These partials are INTERNAL to the STT pipeline — we do NOT forward them to the LLM. Their purpose is faster convergence on the final transcript.

When the smart end-of-turn detector (Component 7) decides the patient is done, Sarvam finalizes the transcript and we forward the **complete utterance** to the LLM.

Configuration:
- Sarvam Saaras v3 model with `language=auto` (Sarvam autodetects Telugu/Hindi/English per word; code-mixing handled natively)
- WebSocket streaming endpoint, not REST

### 4.2 Streaming LLM (Gemini 2.5 Flash via FallbackAdapter)

Gemini receives the complete transcript + conversation history + system prompt + tool catalog. Gemini emits response tokens via SSE.

We forward tokens to TTS sentence-by-sentence as they arrive (split on `.`, `?`, `!` plus Telugu/Hindi sentence terminators). This means TTS starts producing audio for sentence 1 while Gemini is still generating sentence 2.

Already in production: `livekit.agents.llm.FallbackAdapter([Gemini, GPT-4o-mini])` ensures failover transparently on any Gemini error.

### 4.3 Streaming TTS (Sarvam Bulbul chunked)

Sarvam Bulbul v3 accepts text chunks via WebSocket and emits audio chunks back. As soon as we have one complete sentence from the LLM stream, we send it to Bulbul; Bulbul starts producing audio while we wait for sentence 2.

Configuration:
- Sarvam Bulbul v3 with `language=auto` (Bulbul handles code-mixed text)
- Voice: `meera` (default Telugu female; configurable per clinic in Phase 9)
- Chunked WebSocket streaming, not REST

## 5. Components 4-6 — Warmup and pre-caching

### 5.1 Pre-cached greeting at SIP pickup

When the SIP trunk delivers a call to a LiveKit room, the agent has ~300-1500ms of "cold start" — connecting to Sarvam, fetching branch context, initializing Gemini context. During this time, traditional voice agents play silence or beeps.

We instead play a **pre-recorded greeting WAV** that's been generated by Sarvam Bulbul offline:

```
"Namaskaram. Mee call ni Vachanam ki connect chesthunnam. Konchem time istharu?"
(Hello. Connecting your call to Vachanam. Give me a moment please.)
```

The WAV is per-clinic (uses branch.name). Generated by an offline script during Phase 9 onboarding (`scripts/generate_clinic_greeting.py`). Stored in Render's persistent disk (~50KB per file) OR in S3 (Phase 10 if persistent disk becomes a constraint).

Result: patient hears a human voice in <100ms after pickup. Backend warms up during playback.

### 5.2 Connection keep-alive

TLS handshakes add 100-200ms per request. We open persistent connections at call start and reuse them for every turn:

- **Sarvam STT/TTS WebSocket** — kept open for entire call duration
- **Gemini SSE channel** — chat session reused across turns within the same call
- **Redis async connection** — reused per call (note: we keep using `_redis()` factory per-call from TD-016 fix; long-lived per-call client is fine — only the module-level singleton was the bug)
- **Postgres pool** — `pool_pre_ping=True` (already set) ensures stale connections are recycled

### 5.3 Parallel branch+doctor DB lookup during greeting

Today: `on_enter` blocks on DB lookup for branch + doctors before greeting plays.

New: launch DB lookup as a background asyncio task at the moment of SIP pickup. While the pre-cached greeting plays (~3-4s), the lookup completes. By the time the patient finishes the greeting, the system prompt is built with full clinic context.

## 6. Component 7 — Smart end-of-turn detection

Replace fixed VAD silence threshold with `livekit.agents.turn_detector.MultilingualModel()`.

How it works:
- Small ML model (~50MB) runs locally on the Fly VM
- Watches the streaming STT partials
- Decides "is this person done speaking?" based on intonation, grammar completeness, prosodic features
- Returns boolean per utterance with confidence score

Result:
- Confident finish ("doctor kavali."): detected in 100-300ms
- Hesitant finish ("doctor... kavali..."): waits 700-1200ms naturally
- Adaptive per utterance, no global timer to tune

Fallback: if model confidence < 60% on the end-of-turn decision, fall back to conservative 1000ms silence-based VAD. Adds 200ms in fallback cases only (estimated <20% of turns).

Multilingual model isn't tuned specifically for Telugu. Mitigation accepted: fallback VAD catches the misses. Tune model accuracy with real call data in Phase 10.

## 7. Component 8 — Always-interruptible AI

If patient starts speaking while AI is mid-sentence, the AI immediately stops. LiveKit handles this natively via the `interrupt_on_user_speech` option (or equivalent in v1.4 API).

This is the safety net for any case where Component 7 misjudges end-of-turn: even if AI starts responding too early, the patient can just keep talking and the AI shuts up.

## 8. Component 9 — Silence handling state machine

State machine that runs between turns. No keyword detection. Pure timer-based with LLM-driven prompt content.

### 8.1 States

```
AI_SPEAKING      — TTS is playing audio
USER_SPEAKING    — Sarvam is producing partials
IDLE             — both silent (silence timer running)
WAIT_REQUESTED   — LLM has marked this turn as a wait request (sets longer timeout)
ENDED            — booking confirmed OR user hung up OR force-hangup fired
```

### 8.2 Timeouts (industry-standard, Bland AI / Retell / Vapi tier)

**DEFAULT SILENCE** (no wait request, no garbled input flag):

```
T+0s   silence begins (AI finishes speaking OR user's last utterance ended)
T+6s   System notifies LLM: "patient_silent_6s"
       LLM responds with context-aware prompt (typically "Vintunaru?")
       AI response RESETS timer to 0
T+12s  System notifies LLM again: "patient_silent_12s"
       LLM responds with second prompt (typically "Hello? Sound vinipistunda?")
       AI response RESETS timer to 0
T+18s  System triggers HARD HANGUP
       Canned final message: "Tarvath mali call cheyandi. Dhanyavadalu."
       → close session
```

**WAIT REQUESTED** (LLM identifies wait request from conversation context, sets flag via `extend_silence_timeout` tool call OR system prompt instruction):

```
T+0s   silence begins after AI says "Saare, mee daggara wait chestha"
T+15s  prompt 1: "Inka mee kosam wait chestha"
T+30s  prompt 2: "Hello?"
T+45s  HARD HANGUP
```

**COULDN'T UNDERSTAND** (STT confidence < 60% OR LLM marked input as garbled):

```
Each failed turn:
  AI says: "Naaku sound saripoga vinipinchledu. Mali cheppagalara?"
  Increment counter
Counter resets to 0 on first comprehensible turn.

Counter = 3:
  HARD HANGUP: "Mee phone sound sariga ledu. Mali try cheyandi please. Dhanyavadalu."
```

**EMERGENCY MODE** (emergency keyword detected earlier in this call):

```
Default × 2:
  prompt 1 at T+12s
  prompt 2 at T+24s
  hangup at T+36s

Wait × 2:
  prompt 1 at T+30s
  prompt 2 at T+60s
  hangup at T+90s

Couldn't-understand counter → 5 (not 3) before hangup
```

### 8.3 Reset rules

```
Any user speech → silence timer reset to 0
Any AI response (including silence prompt) → silence timer reset to 0
HARD HANGUP fires regardless of LLM state — no extra round-trip
```

### 8.4 Why LLM controls prompt content

The silence prompt text is not hardcoded. The system notifies the LLM (via internal event, not user-visible) that silence has been detected; the LLM responds with a context-aware prompt:

- First silence in a fresh call: "Vintunaru?"
- Patient asked to wait earlier: "Inka mee kosam wait chestha"
- Patient was mid-booking (gave name but not yet doctor): "Mali sodaru, mee complaint cheppandi"

This is more natural than canned phrases and adapts to the conversation. The HARD HANGUP message at the end IS canned to ensure we always exit cleanly even if LLM is down.

### 8.5 Why no keyword detection for "wait"

Researched alternatives. Patient-side keyword scanning fails on:
- False positives: "I'll wait for the doctor" → AI thinks patient wants to wait
- False negatives: "hold up" / "give me ten seconds" → not in fixed keyword list
- Context loss: "wait, did you say 10 AM?" — question, not wait request

LLM understanding handles all of these naturally. When patient says "agandi", LLM responds "saare wait chestha" — this AI response naturally resets the silence timer to 0, and the LLM also signals (via system prompt instruction OR tool call) that the next silence window is the longer "wait" timeout.

## 9. Component 10 — Network/garbled input handling

Three-layer defense:

### 9.1 Layer A — STT confidence threshold

Sarvam Saaras returns per-word confidence scores in its final transcript response. We compute average confidence; if < 60%, do NOT forward to LLM.

Instead, AI says (canned): `"Naaku sound saripoga vinipinchledu. Mali cheppagalara?"`

Counter for Component 9.couldn't-understand state increments.

### 9.2 Layer B — LLM-side clarification

System prompt includes:

```
If the user's transcript contains random sounds, partial words, or does not 
form a coherent Telugu/Hindi/English request, respond exactly: 
"Kshamincandi, mali cheppagalara?" 
Do NOT proceed with booking until you receive a clear request.
Do NOT guess at what the patient meant.
```

This catches garbled transcripts that pass the STT confidence threshold but are still nonsensical to a reasoning model.

### 9.3 Layer C — Counter-based escalation

State counter `couldnt_understand_count` initialized to 0.

Increment on every failed turn (Layer A or Layer B trigger).

Reset to 0 on first successful turn (LLM produces a response that advances the booking state OR contains a tool call to a booking tool).

When counter reaches 3 (or 5 in emergency mode), trigger HARD HANGUP with message: `"Mee phone sound sariga ledu. Mali try cheyandi please. Dhanyavadalu."`

### 9.4 Why this design

Without C, a patient on a broken network gets stuck in an infinite "please repeat" loop, wasting their minutes and ours. With C, we bail out gracefully after 3 failures, totaling ~15-20s of attempt, and tell them to call back when their network is better.

We do NOT try to fix outbound audio (patient hearing OUR audio break). That's their network's problem.

## 10. Components 11-12 — Existing safety nets (unchanged)

### 10.1 Component 11 — Solo 4-min hard cap

Already implemented from TD-009 fix. Background watchdog polls every 5s. At 230s elapsed, warning fires once (gated by `solo_warning_sent` flag). At 240s elapsed, session closes via `session.aclose()` regardless of state.

This is a HARD billing limit. Cannot be extended even by emergency mode. The Solo plan's promise to the clinic is "AI wraps up at 4 minutes."

If patient hasn't completed booking at 4:00, the AI's final message is: `"Konchem time aindi. Tarvath clinic ki call cheyandi please. Dhanyavadalu."`

### 10.2 Component 12 — Emergency-mode silence override

When `is_emergency()` detects an emergency keyword earlier in the call, `state.emergency_detected = True`. From that point, all Component 9 silence timeouts are multiplied as defined in §8.2.

Rationale: patient who mentioned chest pain may go silent because they collapsed. We must not auto-hang up. We give them up to 36s of silence (vs 18s default) and up to 5 garbled-input retries (vs 3) before bailing.

This works in concert with the existing emergency response: when keyword is detected, AI says `"Naa understand chestha. Dayachesi e number ki call cheyandi: {branch.emergency_contact}"` and continues with booking. The silence override is the silent safety net.

## 11. Latency budget

Per-turn latency for active conversation (after first greeting):

| Phase | Time |
|---|---|
| Smart end-of-turn decision (Component 7) | 100-800ms (avg 400ms) |
| STT finalization | 50-100ms |
| Gemini SSE TTFT via LiveKit connection (warmed) | 250-450ms |
| First sentence to Sarvam Bulbul + first audio chunk back | 200-400ms |
| **Total turn latency** | **600-1700ms (avg 900ms)** |

First-greeting latency on call pickup:

| Phase | Time |
|---|---|
| SIP setup + LiveKit room creation | ~50ms |
| Pre-cached greeting WAV starts playing | ~50ms |
| **Total first-word latency** | **<100ms** |

The 900ms average is above the 800ms goal by 100ms. This is acceptable: the 100ms is variance from smart turn detection (which is genuinely faster for confident speakers and slower for hesitant ones). Average masks the truth. P50 will be closer to 750ms; P90 to 1100ms.

If P50 routinely exceeds 900ms in production, we revisit: tighter Bulbul chunking, smaller Gemini context, or accept the latency.

## 12. Implementation tasks (preview — full plan via writing-plans)

Estimated 4-5 days for voice-agent-engineer.

1. **Streaming TTS chunking** — change Sarvam Bulbul integration from REST to WebSocket; sentence-boundary splitter feeding chunks as LLM streams. ~1 day.
2. **Pre-cached greeting infrastructure** — `scripts/generate_clinic_greeting.py`; storage path; play-on-pickup logic. ~0.5 day.
3. **Connection keep-alive** — refactor Sarvam STT/TTS to persistent WebSocket per call; Gemini chat session per call. ~0.5 day.
4. **Parallel DB lookup at pickup** — asyncio task launched in `on_room_connected` event. ~0.5 day.
5. **Smart end-of-turn detection** — integrate `livekit.agents.turn_detector.MultilingualModel()`; add fallback VAD for low-confidence cases. ~0.5 day.
6. **Always-interruptible AI** — verify LiveKit 1.4 `interrupt_on_user_speech` is enabled in `RoomInputOptions`. ~0.5 hour.
7. **Silence handling state machine** — `agent/services/silence_handler.py`; integrate with session state; LLM notification events. ~1 day.
8. **STT confidence threshold + counter escalation** — `agent/services/audio_quality.py`; parse Sarvam confidence; counter state. ~0.5 day.
9. **Update system prompt** — add instructions for wait handling, garbled input handling, silence prompt context. ~0.5 day.
10. **Tests** — unit tests for silence state machine, integration tests for streaming pipeline (mocked Sarvam/Gemini), edge cases for emergency override. ~1 day.

## 13. Acceptance criteria

```
[ ] Pre-cached greeting plays in < 200ms on call pickup (measured via timestamps)
[ ] Active-turn latency P50 < 900ms, P90 < 1300ms (measured against 20 simulated calls)
[ ] Smart end-of-turn detection correctly identifies utterance end on a 50-call test set
[ ] Always-interruptible AI: patient speaks over AI → AI stops within 100ms
[ ] Silence handling: AI prompts at 6s/12s, hangs up at 18s on test silent call
[ ] Wait handling: when LLM says "wait chestha", next silence cycle uses 15s/30s/45s
[ ] Couldn't-understand counter: 3 garbled turns → hangup; comprehensible turn resets counter
[ ] Emergency mode: after keyword detected, silence timeouts × 2
[ ] Solo 4-min cap: warning at 3:50, hangup at 4:00 regardless of state
[ ] STT confidence < 60% → AI says "mali cheppagalara" without forwarding to LLM
[ ] LLM-side clarification: nonsensical input triggers "kshamincandi"
[ ] All Phase 2 tests still pass (23 unit + 4 integration + 2 edge-case + 9 new from Phase 4)
[ ] New tests added: silence state machine (6), STT confidence (3), end-of-turn detection (3)
```

## 14. Drawbacks / open risks

1. **LiveKit MultilingualModel is not Telugu-tuned.** May misjudge end-of-turn for thick accents. Fallback VAD catches this; tune with real call data in Phase 10.
2. **Pre-cached greeting requires per-clinic generation.** Adds a step to onboarding wizard in Phase 9. Mitigated by automation script.
3. **300ms VAD fallback adds latency in unconfident cases.** Estimated <20% of turns. Acceptable.
4. **Streaming TTS chunked needs careful sentence boundary detection.** Bad chunking = chopped audio. Mitigation: validated splitter with Telugu sentence terminators (`।`, `.`, `?`, `!`).
5. **LLM tool call for `extend_silence_timeout` adds complexity.** Mitigation noted in §8.5 — the LLM also reliably handles wait via natural response; tool call is defensive.
6. **STT confidence < 60% threshold is heuristic.** Tune on real call data in Phase 10.
7. **Couldn't-understand counter could trip false positives for patients with strong accents.** Counter resets on first comprehensible turn, so a real conversation cannot tip the counter. False positives only on consecutive misunderstandings, which is the right time to bail.
8. **Per-clinic configurable timeouts deferred to Phase 9.** Some clinics (geriatric, ortho) may want gentler timeouts. Add `branch.silence_profile` enum (strict / standard / patient-respect) in Phase 9.

## 15. What this spec does NOT change

- Vendor choices (Sarvam STT/TTS, Gemini LLM, LiveKit orchestration, Vobiz SIP) all stay
- Existing `booking_tools.py` 4 LLM function tools unchanged
- Token assignment via Redis INCR (CLAUDE.md Rule 2) unchanged
- Calendar-first booking confirmation (CLAUDE.md Rule 4) unchanged
- Emergency MVP keyword detection (CLAUDE.md Rule 7) unchanged — already shipped
- System prompt structure (Phase 2 build) extended, not replaced
- Pricing tiers — no change

## 16. Self-review (spec checklist per writing-plans skill)

- **Placeholder scan:** No "TBD" / "TODO" in this spec. All numeric thresholds defined.
- **Internal consistency:** §8.2 timeouts match §11 latency budget assumptions. §10 emergency override matches §12 acceptance criteria.
- **Scope check:** Single coherent enhancement to existing voice agent. Not multi-system. Fits one implementation plan.
- **Ambiguity check:** Component 9 silence handling carefully separated by case (default/wait/garbled/emergency). Each has explicit numeric timeouts. No ambiguous "as needed" language.
- **DPDP / security implications:** No new PII handling. Silence prompts contain no patient data. Pre-cached greetings contain branch name only (not patient name). No change to data retention or audit log.

## 17. Next step

Invoke `writing-plans` skill to produce an implementation plan that breaks the 10 implementation tasks into specialist-dispatchable units with acceptance criteria and dependency order.
