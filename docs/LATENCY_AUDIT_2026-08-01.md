# Latency audit — 2026-08-01

Scope: whole voice path (call setup → per-turn loop), plus web research on 2026
voice-agent latency practice mapped onto our stack.

**Evidence base.** Every number tagged **[M]** is MEASURED from production
(Fly `vachanam-agent`, Telugu call, session `5deaba26`, 57 turns, agent v250).
Numbers tagged **[E]** are estimates and are labelled as such. Nothing here is
inferred from a benchmark blog and presented as our own measurement.

---

## 1. What a real turn actually costs

Production turn 55 (`kind=tool`, `check_availability`) **[M]**:

| Stage | ms | Note |
|---|---|---|
| `stt_finalize` | 314.0 | Soniox finalize, **Tokyo** |
| `eou_delay` | 386.3 | VAD-only turn end (te has no semantic detector) |
| `commit` | 24.5 | |
| `pre_tool` (commit → tool start) | 1124.0 | LLM deciding to call the tool |
| `tool_ms` | **39.4** | **the database is not the problem** |
| `post_tool` (tool end → audio) | 546.5 | second LLM pass + TTS |
| `llm_ttft` / `llm_runs` / `llm_total` | 629.5 / **3** / 2746.8 | three LLM round-trips |
| `tts_ttfb` | 402.7 | Soniox, **Tokyo** |
| `playout_gap` | 2.0 | |
| `unaccounted` | **638.2** | ~31% of the turn is unattributed |
| **`total_ms` / `from_last_word_ms`** | **2048.3 / 2063.5** | what the caller feels |

Turn 56 (`kind=chat`, no tool) **[M]**: `total_ms=254.7`, `llm_ttft=624.5`,
`llm_runs=1`, `cache_hit=True`.

LLM **[M]**: `gemini-2.5-flash` on Vertex, ttft 0.55–1.06 s,
`prompt_tokens` 9 720–10 579, `prompt_cached_tokens` 8 334–9 472.
TTS **[M]**: Soniox `tts-rt-v1`, ttfb 0.40–0.60 s.
Topology **[M]**: `worker_region=bom media=india-west llm=vertex-asia-south1
stt=soniox-jp tts=soniox-jp`.

**Read this before optimizing anything:** a tool turn spends ~39 ms in our
database and ~1.7 s in LLM round-trips. Tuning SQL, indexes or the pool buys
nothing. The cost is round-trips and geography.

---

## 2. Findings, worst first

### P0-1 — STT and TTS run in Tokyo; everything else is in Mumbai
**Measured.** `stt=soniox-jp tts=soniox-jp` while the worker is `bom` and the
LLM is `vertex-asia-south1`. Every finalize and every synthesis crosses
Mumbai↔Tokyo.

**Verified externally:** Soniox deploys only **US, EU and JP** — there is no
India region, so this is structural, not a misconfiguration
([Soniox docs](https://soniox.com/docs/tts/models)).

LiveKit's own guidance puts agent/model co-location as the **first**
optimization ([LiveKit](https://livekit.com/blog/understand-and-improve-agent-latency)).
We violate it on two of three legs.

- Recoverable: **[E] 250–400 ms per turn**, consistent with our measured
  `stt_finalize` 314 ms and `tts_ttfb` 403 ms both carrying the hop.
- Prior session measurement already concluded a regional STT swap is the *only*
  sub-1s lever — it was never acted on.
- Lever: **Sarvam** — India-hosted, sub-250 ms streaming TTS, strongest Telugu
  of the Indic vendors in 2026 blind evaluation
  ([comparison](https://www.callmissed.com/en/blog/best-voice-ai-apis-indian-languages-2026)).
- **This is cheap to try on v1.12.1:** the Sarvam plugin is already loaded at
  boot (`plugin registered … livekit.plugins.sarvam` **[M]**) and
  `SARVAM_API_KEY` is present on Fly. It is a provider A/B behind the existing
  `_build_stt` / `_build_session_tts` factories, not a rewrite.
- Risk to weigh: Soniox Telugu quality is currently praised by Vinay. Quality
  regression is the real cost — A/B one leg at a time (STT first), never both.

### P0-2 — A tool turn pays 2–3 sequential LLM round-trips
**Measured.** `llm_runs=3`, `llm_total=2746.8 ms` on a turn whose tool took
39 ms. `pre_tool=1124 ms` is the model deciding; `post_tool=546 ms` is it
speaking the result.

- **`max_tool_steps` is not set anywhere** (verified: zero occurrences in
  `agent/`). LiveKit names bounding it as a specific latency control. A third
  run on a single-tool turn is exactly what an unbounded step budget allows.
- Already in place and working: deterministic grounded fast-paths (0 LLM calls),
  cached filler clips masking tool time, `voice_tool_prefetch` for
  `route_to_doctor`.
- **Genuine gap:** the prefetch covers only `route_to_doctor` on booking intent.
  `check_availability` — the most common slow path, and the one measured above —
  is never speculatively started. 2026 practice calls this speculative
  execution: fire the likely query from the *interim* transcript, discard it if
  the guess was wrong, so it can only help
  ([Zylos](https://zylos.ai/research/2026-04-08-speculative-execution-parallel-tool-calling-ai-agents/)).

### P1-3 — 31% of the turn is unattributed
`unaccounted_ms=638.2` **[M]** — computed as `total − known stages`. We cannot
optimize what we do not measure, and this is the second-largest single number in
the table. The trace has no marks around the 2nd/3rd LLM run or the LLM→TTS
handoff, which is where it must be hiding. **Instrument before tuning.**

### P1-4 — Per-turn uncached prompt tokens
**Measured** 9.7–10.6k prompt tokens with 8.3–9.5k cached ⇒ **~1.1–2.2k
uncached tokens every turn**. The cached prefix is doing its job; the
per-call `<private_session_context>` suffix (date table + caller context) is
re-sent uncached on every inference by construction.
Vinay's prompt rewrite roughly halved the cached prompt (4.8–5.1k **[M]** from
the v252 cache-warm logs), which helps cost and TTFT.

### P1-5 — Call setup could block on an LLM call *(introduced today; already fixed)*
`await spoken_map()` sat in the call-setup critical path, so a Redis miss would
have blocked *answering the phone* on a Gemini round-trip. Now a cache-only
lookup with a 250 ms timeout plus background priming. Fixed and tested in this
audit — flagged here because it is exactly the class of bug being hunted.

### P2-6 — Telugu has no semantic turn detector
`MultilingualModel` does not support `te-IN`, so turn-end is VAD-only with
fixed endpointing (`min_delay 0.05 / max_delay 0.3`). Measured `eou_delay`
386 ms. Already tuned aggressively; pushing further risks clipping callers
mid-sentence. **Low headroom — leave it alone.**

### P2-7 — Extra gate query
The billing-cycle lookup added today runs inside the existing
`asyncio.gather` of pre-call reads, so it overlaps rather than serializes, and
only when `hard_block_on_exhaust` is set. Noted for completeness; not a
meaningful cost.

### P2-8 — Reply length is a latency lever
`tts_synth=1732 ms` for `speak_dur=2708 ms` **[M]**. Synthesis streams and
overlaps playout, so this is not dead air — but shorter replies still reach
first audio sooner and give the caller less to interrupt.

---

## 3. Web research mapped to our stack

Industry framing for 2026: sub-500 ms TTFA is the "feels human" bar; a vanilla
LiveKit session sits ~1.2–1.4 s p95, and a well-optimized one ~500–650 ms
([futureagi](https://futureagi.com/blog/how-to-optimize-livekit-latency-2026/)).
Our measured warm chat turn is 255 ms **[M]** and a tool turn 2.05 s **[M]** —
so our problem is **tool turns and geography**, not the base loop.

| Technique (2026 practice) | Us | Verdict |
|---|---|---|
| Agent/model co-location | ❌ STT+TTS in Tokyo | **biggest gap — P0-1** |
| Speculative / parallel tool calling | ⚠️ route only | **extend to availability — P0-2** |
| Bound `max_tool_steps` | ❌ unset | **quick win — P0-2** |
| Prefix / context caching | ✅ Vertex CachedContent, 8–9.5k cached | done |
| Streaming STT, partial/streaming TTS | ✅ | done |
| Filler audio during tool calls | ✅ cached clips | done |
| Preemptive generation | ✅ enabled incl. preemptive TTS | done |
| Aggressive endpointing | ✅ 0.05/0.3 fixed | at practical floor |
| Faster model for routing | ✅ lite model for routing/fallback | done |
| Per-stage observability | ⚠️ 31% unaccounted | **P1-3** |

Notably, most of the standard checklist is **already implemented here**. The
remaining wins are structural, not incremental knob-turning.

---

## 4. Recommended order

1. **Instrument the 638 ms** (P1-3). Cheap, no behaviour change, and it decides
   whether step 3 is even worth doing. Do this first — do not tune blind.
2. **Set `max_tool_steps`** (P0-2). One line; bounds the 3rd LLM run.
3. **Speculative `check_availability`** off the interim transcript (P0-2),
   behind a kill-switch, discard on mismatch.
4. **Sarvam STT A/B in Mumbai** (P0-1). Biggest single win **[E] 250–400 ms**,
   but it is a quality risk on a Telugu path Vinay currently likes — one leg,
   behind a flag, validated by a real call.

**Do not** touch SQL, indexes, the pool, or endpointing: measured tool time is
39 ms and endpointing is already at its practical floor.

---

## 5. Honest limits of this audit

- One production call (57 turns) is the measured base. Prior guidance in this
  repo was to collect ≥30 calls before acting on any knob; that still stands for
  anything with a quality trade-off (item 4 especially).
- Fly's log buffer had rotated, so a broader sample could not be pulled at audit
  time. `lat:last_call` in Redis holds the per-call setup split and should be
  the source for a wider sample.
- The [E] savings for co-location are inferred from the measured Tokyo-carrying
  stages, not from a Mumbai-hosted A/B. Only the A/B settles it.

## 6. Implementation follow-up — code verification

The code trace found four latency defects not visible from the single production
turn, plus one measurement error in the original interpretation.

### Fixed — shared voice caches were silently bypassed

`backend.redis_client.get_redis()` is a synchronous accessor that returns an
async Redis client. The voice worker incorrectly used `await get_redis()` in the
shared prompt cache, greeting cache, clinic roster cache, switch telemetry, call
setup telemetry, and turn telemetry. The resulting `TypeError` was swallowed by
best-effort cache handlers. Consequences:

- another worker's Vertex CachedContent resource was not reused;
- cached greeting audio was not read or written;
- the clinic roster cache fell back to PostgreSQL on every call;
- durable latency evidence could silently disappear.

All callers now obtain the shared client synchronously and await only Redis
commands. Regression tests exercise the real contract instead of source-only
assertions.

### Fixed — Redis connection and slot-query amplification

Booking tools created a new `rediss://` client for every operation and closed it
again. That repeatedly pays connection-pool/TLS/AUTH setup against Upstash. They
now reuse the existing event-loop-local client. Appointment availability also
performed one sequential Redis `GET` per generated slot; a doctor with several
sessions could therefore turn one availability check into dozens of network
round trips. It now issues one `MGET` for every slot counter.

This does not change availability semantics: DB-confirmed occupancy is still
the authoritative floor, Redis remains the atomic hold gate, and held-slot
adjustment is applied after the batched read exactly as before.

### Fixed — the safety stream delayed clean speech

The internal-tool-speech firewall retained the first 24 characters of every LLM
reply before releasing anything to TTS. Short answers could finish generation
before Soniox received their first text. It now retains only a trailing fragment
that can still become a protected marker on the next chunk (for example
`check_avai`), while ordinary patient-safe text streams immediately. Split-marker
and immediate-first-chunk tests both pass.

### Fixed — pathological tool-loop ceiling

LiveKit 1.6.6 defaults to three consecutive tool steps. Production now allows
two: enough for the valid `route -> availability` and `hold -> confirm` pairs,
but a third same-turn tool step is forced to a final response instead of paying
another avoidable Gemini round trip.

Important correction: `llm_runs=3` does **not** prove three tool steps. It may be
a cancelled preemptive draft, the committed tool-call generation, and the
required post-tool response. Therefore `max_tool_steps=1` would risk breaking
bookings and would not remove the required post-tool pass.

### Fixed — `unaccounted_ms` was not a valid wall-clock gap

The old formula subtracted LLM TTFT and TTS TTFB as if they were sequential.
With preemptive TTS those durations overlap, so the 638 ms figure could be an
arithmetic residual rather than idle time. The trace now partitions exact,
non-overlapping spans and emits `commit_to_tts_ms` and `tool_span_ms`. Provider
TTFT/TTFB remain useful diagnostics but are not added together as wall time.

### Deliberately not implemented

- Speculative `check_availability` parsing was not added. The measured tool is
  39 ms; guessing multilingual doctor/date/time arguments to save at most that
  amount adds a correctness risk to a legally sensitive path.
- Endpoint silence was not reduced below the current 60 ms VAD signal plus the
  Soniox-supported 200 ms finalization guard. The previous more aggressive
  combination damaged Telugu names and split utterances.
- Sarvam was not promoted without a real Telugu A/B. It remains a reversible
  STT-only experiment, but prior calls found it slower and Soniox quality is a
  stated product requirement.

### Remaining structural floor

The largest irreducible costs in the current stack remain Soniox Japan
finalization and first audio, plus the two model passes required by a generic
LLM-mediated tool turn. These code fixes remove cache misses, connection setup,
query amplification, sanitizer buffering, and runaway tool tails; they do not
make a Tokyo provider co-located with Mumbai. Production before/after calls are
required for honest p50/p95 savings. The next trace now has the fields needed to
measure that comparison correctly.