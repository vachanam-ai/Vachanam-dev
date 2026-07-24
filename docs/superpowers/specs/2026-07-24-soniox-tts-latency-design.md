# Soniox TTS switch + feasible latency techniques — design

**Date:** 2026-07-24 · **Owner:** Vinay · **Author:** Claude
**Supersedes intent of:** the reverted TTFA experiments (commit `4932c49`)

## Goal

Latency is the #1 concern (third attempt — "let's get it this time"). Move
production TTS to Soniox (Vinay: better voice, and Soniox faster than Sarvam),
keep smallest.ai as fallback, and implement only the latency techniques that
are actually *feasible and move the needle* on this pipeline. Drop Soniox voice
cloning (not good enough). Remove Odia.

## Ground truth (measured, this session)

- The latency floor is Soniox STT endpoint (Mumbai→Tokyo ~260ms RTT + ~200ms
  silence guard + finalize), NOT the LLM/TTS pipeline. LLM ttft (Vertex Mumbai
  2.5-flash) ~0.55–0.67s and TTS ttfb are flat. ([[project-speed-sandbox-floor]])
- Prod STT is **already on the Soniox JP edge** (`SONIOX_WS_URL` prod secret set;
  #406). The regional STT win is already banked; Tokyo RTT is irreducible for
  Soniox (no India region).
- Prod LLM prefix caching is **already done** via #417 explicit Vertex
  CachedContent (~0.2s off every turn).
- Soniox TTS TTFB measured ~550–620ms in sandbox — but that was **cold WS
  connect**. Native token streaming + a prewarmed WS connection is what makes it
  latency-viable vs the current smallest path (~170ms). #8 prewarm is therefore
  a hard requirement of the switch, not an optional nicety.

## The 12 techniques — feasibility verdict

| # | Technique | Verdict | Action |
|---|---|---|---|
| 1 | Streaming STT + preemptive | done | prove (assert `preemptive_generation=True`) |
| 2 | Partial LLM→TTS | done | prove (Soniox streams natively; smallest WS) |
| 3 | Prompt prefix cache | done (#417 Vertex) | prove (existing cache test) |
| 4 | Tiered model routing | **skip** | feasible but LLM not the bottleneck; gain ≈0, adds a prod branch |
| 5 | Tool prefetch on intent | **BUILD** | parallel `check_slot_availability`, branch-scoped, cancel-safe |
| 6 | Audio prebuffer / AEC | N/A | PSTN via Vobiz SIP, no WebRTC AEC path — document |
| 7 | Async eval (no sync judge) | done | policy ([[feedback-no-auto-prompt-tuning]]) |
| 8 | TTS prewarm | **BUILD** | warm Soniox WS in `_prewarm`; essential for the switch |
| 9 | Nano model for acks | **skip** | same as #4 |
| 10 | Semantic cache → cached audio | **REFUSED** | = deterministic audio injection, banned ([[feedback-latency-guardrails]]) |
| 11 | KV/prefix reuse across turns | done | AgentSession stable chat_ctx |
| 12 | Regional STT/TTS | done/partial | STT JP ✅, LLM Mumbai ✅; Soniox TTS on global until JP-TTS is enabled on the account (Vinay account action; key is region-scoped, JP-TTS currently 401s) |

## Architecture — TTS provider seam (Approach A)

Global `TTS_PROVIDER` setting (default `soniox`), no DB migration.
`_build_session_tts(voice_id, tts_lang)` branches:

- `soniox` → `FallbackAdapter([SonioxTTS(streaming), _StreamingSmallestTTS, _HttpSmallestTTS])`
  — Soniox primary, smallest as RULE-8 fallback (WS then REST).
- `smallest` → today's behavior unchanged (instant rollback path).

Voice: `Branch.tts_voice` reused. When provider=soniox and the stored value is
empty or not a Soniox voice, fall back to `soniox_tts_default_voice` (Priya).
No cloning → no writes to `tts_voice` from a Soniox clone flow; existing smallest
ids simply resolve to the default Soniox catalog voice.

RULE 6 (sanitization) unchanged: Soniox TTS receives Telugu script, same script
guard already applied before TTS.

### New config (`backend/config.py`)
`tts_provider: str = "soniox"`, `soniox_tts_model = "tts-rt-v1"`,
`soniox_tts_ws_url = "wss://tts-rt.soniox.com/tts-websocket"` (global; JP override
via env once enabled), `soniox_tts_default_voice = "Priya"`,
`soniox_tts_sample_rate = 24000`.

## #8 TTS prewarm

Build the Soniox TTS object in `_prewarm` → `proc.userdata["tts_soniox"]`; the
entrypoint reuses it instead of constructing per call, so the WS auth/connect is
off the caller's first turn. Fallback: if prewarm missed, entrypoint builds it.
(Clinic voice is per-branch, so prewarm builds the DEFAULT-voice TTS; a
non-default branch rebuilds — most clinics use the default, so the warm path
covers the common case. ponytail: default-voice warm only; per-branch warm is a
later optimization if a big clinic uses a custom voice.)

## #5 tool prefetch

On `on_user_turn_completed`, if the committed transcript maps to a
high-confidence booking/slot intent, fire `_check_slots(...)` in parallel with
the LLM as `self._prefetch` (asyncio task). `check_slot_availability` awaits the
prefetched task if present (and clears it), else runs normally. Guards:
- **RULE 1**: prefetch keyed strictly to THIS session's `branch_id`; never a
  shared/global cache.
- Cancel `self._prefetch` if the LLM picks a different tool or the turn ends, so
  tasks never leak under load.

## Remove Odia

Delete the `"or"` entry from `agent/i18n/languages.py` LANGUAGES; drop `or` from
the `niharika` voice comment; remove Odia from frontend language/voice pickers
(`VoicePicker.jsx`, `Settings.jsx`, `Landing.jsx`) and tests. Platform goes 8→7
languages (te/hi/ta/kn/ml/mr/bn). **Flag:** CLAUDE.md pricing copy says "all 8" —
Vinay to confirm marketing copy update to "all 7".

## Testing (TDD — failing test first for every BUILD)

- TTS seam: `_build_session_tts` returns Soniox-primary FallbackAdapter when
  `TTS_PROVIDER=soniox`; smallest when `smallest`; default-voice substitution.
- #8: prewarm populates `tts_soniox`; entrypoint reuses it.
- #5: prefetch fires on booking intent; `check_slot_availability` consumes it;
  prefetch cancelled on tool mismatch; prefetch never crosses `branch_id`.
- Odia: `get_lang("or")` no longer returns an Odia config; language list == 7.
- Prove-done: assertion tests pinning #1/#2/#3/#7/#11/#12 live config.

## Safety / rollout

- Soniox TTS wrapped in FallbackAdapter (RULE 8): Soniox down → smallest, call
  never dies.
- `TTS_PROVIDER=smallest` = instant rollback, no deploy.
- #5 strictly branch-scoped (RULE 1) + cancel-safe (no task leaks).
- Deploy gated on green full suite; STATUS/FIXLOG/memory updated.

## Out of scope

Soniox voice cloning (dropped), #4/#9 tiered routing (no gain), #10 (banned).
