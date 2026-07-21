# TTFA Deep Review — 2026-07-22

Principal-engineer review of the voice turn latency, grounded in the actual
codebase, FIXLOG measurements, and the failed-experiment history. Companion to
`docs/superpowers/plans/2026-07-21-persistent-voice-latency-plan.md`.

## 1. Premise corrections (the review request vs reality)

| Claim in request | Reality |
|---|---|
| FastAPI + WebSockets orchestration | Voice plane is **LiveKit Agents** on Fly bom; FastAPI (Render) is dashboard-only, never in the turn path |
| STT ~700ms | The 0.7-1.0s is mostly **endpoint WAIT** (deciding the caller finished), not transcription. Soniox streams transcripts live |
| Gemini ~1000ms | Measured 0.67s TTFT on Vertex Mumbai since #404. The 1.0-1.3s figure is the retired global-endpoint path |
| Total ~3s | Perceived ~2.5-3s (Vinay's calls); **measured stages sum to ~1.6-2.3s**. Up to ~1s is UNATTRIBUTED — that gap, not any single stage, is the current bottleneck |
| "Overlap STT/LLM/TTS more" | Already overlapped: `preemptive_generation=True` (agent.py:4085) starts the LLM on the interim transcript; TTS streams sentence-by-sentence; lead-in rule (#387) makes the first TTS chunk tiny |

## 2. Already shipped — do not re-propose

Every generic recommendation in the standard playbook is already deployed:

- **Endpointing**: LiveKit 0.05/0.3s (agent.py:4098-4099); Soniox semantic endpoint level 1 (#442, Fly v149)
- **LLM**: Vertex Mumbai 2.5-flash, thinking disabled, ttft 0.67s (#404); global-key fallbacks (RULE 8)
- **Prompt**: real-prompt prewarm during greeting (#393); explicit Vertex prompt cache for eligible calls (#417)
- **TTS**: smallest.ai WS streaming primary + connection pool + warm probe (#405); REST fallback
- **Call start**: 13.95s → fixed — roster cached (#432), Neon kept warm (#435), setup reads gathered (#390)
- **Tool turns**: cached filler clips during slow tools (#361+)
- **Redis**: shared client (#305 — per-call TLS clients OOM'd the box)

**Banned by production evidence — refuse to retry:**
- Aggressive endpoint tuning (800ms cap + sensitivity 0.3): corrupted Telugu — "కరిష్మా"→"హరీష్ కుమార్", fragmented utterances (#399)
- Deterministic audio injection / thinking-ack: two designs, two live misfires — fillers after every sentence (#397, #399)
- Prompt diet: measured worthless (#394-#399 arc)

## 3. The real per-turn budget (warm, non-tool, Telugu PSTN)

```
caller stops speaking (physical)
├─ PSTN→Vobiz→LiveKit India West→Fly bom     ~50-100ms   fixed, in-region
├─ Soniox endpoint decision (level 1)         ~400-800ms  Tokyo RTT inside it
├─ LiveKit commit window (0.05-0.3s)          ~50-300ms   overlaps above
├─ LLM TTFT (Vertex Mumbai, preemptive)       ~670ms      0 if preemptive HIT
├─ speech-guard 24-char carry (agent.py:460)  UNMEASURED  suspect
├─ TTS TTFB (smallest WS, warm)               ~250-500ms
└─ playout + return leg                       ~100-200ms  fixed
                              sequential sum ≈ 1.6-2.3s
                              perceived      ≈ 2.5-3.0s
                              UNACCOUNTED    ≈ 0.5-1.0s  ← the real target
```

## 4. Findings

**F1 — Metrics are not joined per turn. Severity: blocker.**
`lat_eou`/`lat_llm`/`lat_tts` are separate lines (agent.py:4184-4194) — cannot
attribute the missing ~1s. Every tuning decision made without this is a guess,
and guesses here have historically SHIPPED REGRESSIONS (#394→#399). Fix =
plan Phase 1 (TurnLatencyTrace + report script). Saving: 0ms directly; unlocks
everything else.

**F2 — Preemptive-generation cancel rate is unknown. Prime suspect.**
`preemptive_generation=True` starts the LLM on the interim transcript. If the
FINAL transcript differs, LiveKit cancels and regenerates — paying TTFT twice
(~1.3s instead of ~0.67s, or worse: TTFT after the endpoint wait instead of
overlapped with it). Telugu interims are volatile; the cancel rate could be
high. This alone could BE the unaccounted second. Phase 1 trace item 5 measures
it. If high: the fix is prompt/transcript-stability work, not more endpoint
tuning. Potential saving: 300-700ms on affected turns.

**F3 — Prompt cache excludes known callers (#417 design).**
Calls with caller-specific context (known patient, outbound purpose) skip the
Vertex explicit cache — precisely the repeat customers who call most. Vertex
rejects tools+system alongside cached_content, hence the exclusion. Fix = plan
Task 3.1: split stable instruction/tool prefix (cached) from a small per-call
private context message. Saving: 150-400ms TTFT on known-caller turns. Gate:
prompt-injection + private-speech tests unchanged.

**F4 — Speech-guard fixed 24-char carry (agent.py:460).**
Holds text back before TTS to catch split internal markers. At Telugu token
rates this may cost 50-150ms before the first TTS byte. Task 3.2: measure
`first_llm_token → first_guard_yield`; if >100ms p50, replace with prefix-aware
streaming matcher. The marker-split security test must stay green at every
character boundary. Saving: 50-150ms.

**F5 — Booking/reschedule/cancel pay a SECOND full LLM turn.**
Tool returns → LLM composes the confirmation → TTS. That second pass costs
~1.5-2.5s on the most valuable turns of the product. The uncommitted WIP diff
(agent.py:2630, 2736 — "ask them to come on time") makes this second pass do
MORE work. Fix = plan Task 6.3: deterministic native-script `spoken_response`
from the successful mutation, played directly, post-tool LLM reply suppressed.
Templates per language, existing sanitizers, speech only after atomic write +
calendar write (constraint 6). Saving: 1.5-2.5s on confirm turns. This also
subsumes the WIP diff — the template includes the come-on-time line for free.

**F6 — Soniox endpoint wait is the largest honest stage.**
Level 1 deployed 07-21, unmeasured since. Level 2 (S1 arm) is the one remaining
safe knob; run ONLY as a one-variable arm on the fixed corpus with entity
gates. Saving: 100-300ms if it passes. Sarvam A/B (S5) exists as zero-cost
fallback arm. Soniox has no India endpoint — Tokyo RTT (~130ms) is embedded in
every finalize; only a provider change removes it (Phase 7, last resort).

**F7 — Regions: one unverified link.**
Voice plane is fully co-located: Fly bom + LiveKit India West + Vertex Mumbai +
Vobiz India. Render (Singapore) is out of the turn path. Neon: call-start only,
cached+warm. **Upstash region unverified** — Redis sits in tool turns (atomic
token INCR, holds) and fillers; Mumbai ≈1-3ms, Singapore ≈50-80ms per op,
several ops per tool turn. Action: check REDIS_URL region; if not ap-south-1,
migrate. Saving: 0 or ~100-200ms per tool turn.

**F8 — No further orchestration fat found.**
Setup reads gathered (#390), shared Redis client (#305), TTS pooled/warmed
(#405), notifications already fire-and-forget (constraint 4). The sequential
chain that remains is the honest pipeline.

## 5. Us vs OpenAI Voice / Gemini Live / Retell / Vapi

What they do differently, and why we mostly can't:

1. **Speech-to-speech native models** (OpenAI Realtime, Gemini Live): no
   STT→LLM→TTS chain at all; TTFA 500-800ms. Cost: Telugu clinic-entity
   accuracy unproven, weaker tool grounding, no Soniox-grade transcript for
   the booking record, vendor lock. Not for MVP; worth ONE pilot arm post-plan.
2. **en-US STT endpointing** (Deepgram US-East ~300ms endpoint) is structurally
   ahead of Telugu-capable PSTN STT. Retell/Vapi's quoted ~800-1200ms TTFA is
   an en-US number. Our floor is higher because our language is harder — this
   is a fact to price in, not an engineering failure.
3. **Speculative TTS on interim transcripts** (speak before turn commit,
   cancel on revision): they accept talking over callers occasionally. Our
   callers are patients; #399 proved premature commitment corrupts the
   interaction. Rejected.
4. **Filler audio injection**: Retell-style "hmm" injection = our banned
   thinking-ack (two live failures). Prompt-side lead-in (#387) is our
   equivalent and it works.
5. What we do that they don't: booking truth before speech (constraint 6),
   atomic token guarantee, tenant isolation. These cost latency and are
   non-negotiable.

## 6. Verdict on <1s TTFA

**Not achievable for this product without breaking it, and the request's ~3s
premise is already stale.** The honest physics: ~150-300ms fixed transport +
400-800ms Telugu endpoint decision + 670ms TTFT (0 when preemptive hits) +
250ms TTS + guard. Floor with every remaining lever landed ≈ **1.1-1.4s p50**
on warm conversational turns — which matches the existing plan's 1.3s target.
Sub-1s requires speech-to-speech models (Telugu risk) or the banned levers
(proven regressions). The plan's targets stand; chasing the last 300ms today
buys another #399.

Where sub-1s IS reachable: **F5 deterministic confirm turns** — tool completion
→ first audio ≈ 0.3-0.5s (no LLM in the path). The most valuable turn in the
product becomes the fastest.

## 7. Roadmap (highest impact first)

| # | Action | Expected p50 after (warm conversational / booking-confirm) |
|---|---|---|
| 0 | today (v149) | ~2.5-3.0s perceived, ~1s unattributed |
| 1 | Phase 1 instrumentation + baseline corpus | unchanged; gap attributed |
| 2 | Fix measured dominant hidden buffer (F2 likely) | ~1.8-2.2s / — |
| 3 | Prompt-cache split for known callers (F3) | ~1.7-2.0s / — |
| 4 | Deterministic success lines (F5) | — / **~1.3s total, 0.3-0.5s post-tool** |
| 5 | Guard streaming matcher if F4 measured >100ms | −50-150ms |
| 6 | Soniox level 2 arm (F6), entity-gated | ~1.4-1.7s / — |
| 7 | Upstash region check (F7) | tool turns −0-200ms |
| 8 | Sarvam A/B → new-provider benchmark, only if still failing | last resort |

Each step: one variable, fixed corpus, p50/p95, entity gates, env rollback —
per the plan's rollout procedure. Steps 2/5/6 skipped automatically if Phase 1
shows their stage inside budget.

## 8. Discrepancy chased — resolved against the plan (self-correction)

First draft of this review flagged the plan's baseline ("manual finalize
200ms active") as contradicting prod (v149 startup log `manual_finalize=0`).
Wrong: #443 (commit 18ce737, deployed AFTER v149) enabled manual finalize —
`soniox_manual_finalize_delay_ms` defaults to 200 (backend/config.py:30) and
STATUS's release header confirms the profile. The plan's S0 is correct.
Lesson kept in the doc deliberately: two adjacent STATUS entries described two
different deploys; always resolve baseline claims against config + the LATEST
release entry, not the first matching log line.
