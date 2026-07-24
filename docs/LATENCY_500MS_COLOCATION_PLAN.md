# Voice latency and colocation plan

Updated: 2026-07-25

## Production deployment

Deployed as commit `ec4e90f`, Fly version **178**, on 2026-07-25. Runtime logs
prove the active machine is in `bom`, LiveKit registered the worker in
`India West`, Vertex is `asia-south1`, Soniox STT/TTS are `jp`, the local VAD
signal is 60 ms, preemptive TTS is enabled, all six DID greeting routes loaded,
and every job process prewarmed its persistent Soniox TTS socket. No process
initialization errors occurred. The deployment is complete; the remaining gate
is a real-call corpus of at least 30 Telugu turns.

## Definition of the target

The product target is **500 ms warm perceived response latency**, measured from
the caller's last audible word to the first agent audio at the LiveKit playout
queue. It is not the sum of provider dashboard medians, and it excludes the
unobservable final PSTN handset leg.

The production baseline before this change, from 118 durable turns, was:

| Stage | p50 | p95 |
|---|---:|---:|
| Last recognized word → queued response audio | 1,363 ms | 1,961 ms |
| VAD/interim hangover | 234 ms | 435 ms |
| LLM time to first token | 560 ms | 715 ms |
| TTS time to first audio | 370 ms | 603 ms |
| First turn total | 1,438 ms | 2,572 ms |

The latest startup trace was 4.22 seconds to full session build: 2.00 seconds
for the authoritative tenant lookup, 1.78 seconds for supporting reads, and
0.44 seconds for the rest.

## Region topology

| Component | Region | Enforcement |
|---|---|---|
| Fly voice worker | Mumbai (`bom`) | `infra/fly.agent.toml` |
| LiveKit media/worker dispatch | India West | verified in worker registration logs |
| Vertex turn LLM | Mumbai (`asia-south1`) | constructor constant + tests |
| Soniox STT and TTS | Japan | Japan-only key and JP WebSocket URLs |

This is the closest topology available while Soniox is the mandatory voice
provider. Soniox publicly offers US, EU, and Japan regional processing, not an
India endpoint. LiveKit Cloud can pin telephony/media to India, but project/SIP
region pinning is a LiveKit control-plane setting rather than application code.

References:

- https://docs.livekit.io/deploy/admin/regions/region-pinning/
- https://docs.livekit.io/telephony/features/region-pinning/
- https://soniox.com/docs/data-residency

## Implemented critical path

1. **60 ms local turn signal.** Silero's silence detector is set to 60 ms.
   It is only an early signal. A separate cancellable 200 ms Soniox finalize
   guard remains, so a caller resuming after a natural Telugu pause cancels the
   finalize instead of having a fragment committed.
2. **LLM and TTS overlap.** LiveKit preemptive generation now includes TTS.
   Soniox synthesis starts on a stable preflight transcript while the turn is
   still being confirmed. If the transcript changes, the speculative response
   is discarded. Answer text and booking behavior are unchanged.
3. **Faster first TTS chunk.** Short first sentences are emitted at 8 characters
   instead of being merged into the next sentence by the plugin's 20-character
   default. Sentence boundaries and expressive tags are retained.
4. **No fake LLM warm request.** Production showed first-turn LLM p50 of 557 ms
   versus 561 ms later. The dummy request had no measurable benefit and could
   compete with a fast caller's real request, so it was removed.
5. **Exact-variant Vertex prompt caching.** Recording, known-caller, and outbound
   prompts now receive separate digest-keyed cache variants. The byte-equality
   check remains the final safety gate.
6. **Connection warmup moved earlier.** The persistent Japan Soniox TTS socket
   opens while tenant and caller data are loading, not after the 4.22-second
   build path.
7. **Startup lookup removed from first-audio path.** Each warm job process loads
   a small, non-patient DID-to-public-clinic-greeting map before accepting a job.
   The real opening begins from this map while the authoritative database query
   runs. A mismatch cancels the cached route; fallback-DID calls never use it.

LiveKit documents preemptive TTS as its lowest-latency pipeline option:
https://docs.livekit.io/agents/multimodality/audio/#preemptive-speech-generation

## What colocation cannot do

Colocation removes network hops; it does not force Gemini to produce a first
token in 200 ms or Soniox to produce audio in 135 ms. With the current measured
560 ms LLM and 370 ms TTS medians, a serial pipeline cannot reach 500 ms.
The only credible path is to do most of that work before end-of-turn commitment,
which is why speculative LLM+TTS is the central change.

Gemini 2.5 Flash-Lite is faster but is not served from `asia-south1` according
to Google's current regional model page. Moving it to a US/EU region would undo
colocation and changing the model without a Telugu/tool-call quality evaluation
would violate the no-quality-loss requirement.

## Production acceptance gates

After deployment, collect at least 30 real Telugu turns and compare the same
durable `voice_turn_latency` fields.

| Gate | Target | Rollback condition |
|---|---:|---|
| Answer → first greeting audio, warm p50 | ≤500 ms | p95 >1,000 ms |
| Local VAD silence setting | 60 ms | any repeatable clipped utterance |
| Last word → response audio p50 | ≤700 ms, stretch 500 ms | no improvement or quality regression |
| Last word → response audio p95 | ≤1,200 ms | >1,800 ms |
| Preemptive regeneration rate | <25% | >40% |
| Telugu transcript integrity | no new fragment/name regression | any repeatable corruption |
| Booking/reschedule correctness | 100% existing tests and live script | any wrong mutation |

The 200 ms LLM TTFT request remains a stretch target, not a truthful current
SLO. If preemptive overlap still cannot deliver the 500 ms perceived target,
the next decision is provider/model architecture: a quality-tested faster model
or provisioned regional inference. It is not another silence-timer reduction.

## Rollback

The behavior changes are isolated:

- restore the default VAD with `_load_vad()`;
- set `preemptive_tts` to `False` while keeping preemptive LLM enabled;
- remove the prewarmed greeting route and fall back to post-DB greeting startup;
- retain the Japan endpoints and Mumbai deployment in every rollback.
