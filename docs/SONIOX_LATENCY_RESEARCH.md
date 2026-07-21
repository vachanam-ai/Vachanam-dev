# Soniox turn-latency research and Telugu STT market comparison

**Research date:** 2026-07-21  
**Scope:** Speech-to-text finalization latency for Vachanam's Telugu telephone calls.  
**Status:** Implemented as FIXLOG #442. The initial production profile changes
one variable only: endpoint latency adjustment level 1. The existing 2000 ms
tail cap and Soniox sensitivity default remain unchanged. The safer 200 ms+
manual-finalize path and provider A/B switch are implemented but disabled by
default.

## Implementation outcome (2026-07-21)

- The complete LiveKit dependency train is pinned to 1.6.6, including the
  Soniox plugin, so the endpoint-latency field is available and the plugin can
  emit preflight transcripts before Soniox declares an endpoint.
- SONIOX_ENDPOINT_LATENCY_LEVEL=1 is the only active tuning change.
- SONIOX_MAX_ENDPOINT_DELAY_MS=2000 remains the vendor/plugin default.
- SONIOX_ENDPOINT_SENSITIVITY remains unset.
- SONIOX_MANUAL_FINALIZE_DELAY_MS=0 remains disabled. If enabled later, config
  rejects delays below 200 ms and the timer is cancelled if speech resumes.
- Manual-finalize controllers are scoped to one call and shared only across
  that call's language handoffs; a call can never finalize another call's STT.
- STT_PROVIDER=auto|soniox|sarvam provides an immediate,
  credential-preserving provider rollback/A-B control.
- Worker startup logs the installed LiveKit/Soniox versions and effective
  endpoint profile, preventing a requirements-only change from being mistaken
  for a live runtime change.
- Regression coverage includes the STT factory, config bounds, VAD resume and
  cancellation, cross-call isolation, language handoff, and source guards
  against reintroducing the failed immediate-finalize experiment.
- Deployed as Fly release v149 from commit 9d4d7e5. Production startup evidence:
  Agents 1.6.6, Soniox 1.6.6, level 1, cap 2000 ms, sensitivity unset, manual
  finalize 0; inference and job processes initialized and the worker registered
  with LiveKit India West at 2026-07-21 04:44:57 UTC.

## Decision in one page

Yes, Soniox can probably be made faster without immediately replacing it.

The current production sample shows Soniox taking approximately **0.61–0.90 seconds from end of speech to the usable transcript/end-of-utterance event**. That is already below one second, but it consumes most of a sub-second *whole-turn* budget. Soniox exposes two mechanisms that Vachanam has not yet tested correctly:

1. `endpoint_latency_adjustment_level` selects a lower-latency semantic endpointing profile. Soniox says to use this as the first tuning control. The running LiveKit Soniox package, 1.6.5, cannot pass this field. LiveKit 1.6.6 added it, and the repository now pins the 1.6.6 package, but the production image must actually be rebuilt before it exists at runtime.
2. Manual finalization can be sent after client-side VAD detects speech end. Soniox explicitly says to send about **200 ms of silence after speech** before `finalize`; sending it too early can reduce accuracy.

The failed 2026-07-18 Vachanam experiment does **not** prove that every faster Soniox configuration is inaccurate. It changed three independent variables together:

- `max_endpoint_delay_ms=800`
- `endpoint_sensitivity=0.3`
- immediate forced finalization at the VAD transition

That experiment produced broken Telugu names and fragmented utterances, so reverting it was correct. However, it cannot identify which of the three changes caused the regression. Immediate finalization also conflicts with Soniox's current recommendation to include about 200 ms of trailing silence.

The recommended order is therefore:

1. Deploy/verify LiveKit Soniox 1.6.6, then test `endpoint_latency_adjustment_level=1` **by itself**.
2. If accurate, test level `2` by itself.
3. Separately test VAD-triggered manual finalization after 200 ms of continuing silence, cancelling it if speech resumes.
4. Use `max_endpoint_delay_ms` only as a tail-latency ceiling, not as the primary median-latency control.
5. If Soniox cannot meet the accuracy and latency gate, A/B **Sarvam Saaras v3**, **Smallest Pulse**, **Deepgram Nova-3**, and **ElevenLabs Scribe v2 Realtime** on the same real telephone corpus.

For an alternative provider, Sarvam is the fastest engineering experiment because it is already Vachanam's fallback. Smallest Pulse has an India endpoint and attractive published TTFT, but Telugu support is new and marked Beta. Deepgram Nova-3 has credible low streaming latency and now supports Telugu, but its fastest integrated turn-taking model, Flux, does **not** support Telugu. ElevenLabs advertises approximately 150 ms realtime latency and supports Telugu, but its published number is transcript latency rather than guaranteed end-of-turn latency.

## What is actually slow in Vachanam

The production observations collected before this research were:

| Stage | Observed production range | Meaning |
|---|---:|---|
| Soniox end-of-speech/final transcript | 0.61–0.90 s | Time consumed before the LLM can safely act on the completed caller turn |
| Gemini time to first token | 0.80–1.40 s | The model was receiving roughly 17.7k–17.9k prompt tokens; observed cache tokens were zero |
| Smallest TTS time to first audio | about 0.18 s at best | Audio synthesis startup after speakable text exists |

These stages create a useful lower-bound calculation:

```text
best observed sequential path
= 0.61 s STT finalization
+ 0.80 s LLM first token
+ 0.18 s TTS first audio
= 1.59 s before transport/playout overhead
```

Therefore, **Soniox tuning alone cannot make the complete caller-stop-to-agent-audio interval less than one second with the current LLM behavior**. Even eliminating Soniox latency entirely would leave approximately 0.98 seconds before normal scheduling and audio transport.

Soniox is still worth improving because reducing its 0.61–0.90 seconds to an engineering target of roughly 0.25–0.50 seconds could save 0.2–0.6 seconds on every turn. That target is an inference from Soniox's 200 ms manual-finalization guidance and Vachanam's measured baseline; Soniox does not publish a guaranteed Telugu endpoint-latency number for each adjustment level.

To make the *whole turn* less than one second, the pipeline needs a budget such as:

| Budget item | Target p50 |
|---|---:|
| STT end-of-turn/commit | 0.30 s |
| LLM to first speakable fragment | 0.30 s |
| TTS first audio | 0.20 s |
| scheduling, network and playout margin | 0.10 s |
| **Total** | **0.90 s** |

This makes sub-second p50 plausible only if STT is shortened **and** the LLM prompt/cache/speculation path is fixed. Sub-second p95 is a materially harder target and should not be promised before real-call measurement.

## Soniox: what the service really exposes

Soniox uses semantic endpointing: it considers pauses, intonation, speech patterns, and conversational context instead of using silence alone. An endpoint finalizes the segment and emits a final `<end>` token. More aggressive settings can finalize sooner, but may reduce recognition accuracy and split long speech into more segments. See the [Soniox endpoint detection documentation](https://soniox.com/docs/stt/rt/endpoint-detection).

### The three automatic endpoint controls

| Control | Range/default in Soniox API | What it does | Correct use in Vachanam |
|---|---|---|---|
| `endpoint_latency_adjustment_level` | 0–3; default 0 | Selects progressively faster semantic endpoint profiles | Test this first, one level at a time |
| `endpoint_sensitivity` | -1.0–1.0; default 0 | Changes how likely the model is to emit an endpoint at the selected profile | Test only after choosing a latency level |
| `max_endpoint_delay_ms` | 500–3000; API default 2000 | Hard upper bound after speech ends | Control p95/tail; it is not a target and may not lower p50 |

Soniox's example lower-latency configuration is level 2, sensitivity 0.3, and maximum delay 1500 ms. That is a generic starting point, not evidence that this combination is safe for Telugu clinic calls. Soniox's own best practices say to start from defaults, tune on real conversations, use latency adjustment first, sensitivity second, and the maximum delay only when a hard bound is required.

### Manual finalization

The WebSocket accepts:

```json
{"type": "finalize"}
```

It finalizes received audio, returns all tokens as final, and emits `<fin>`. The important accuracy requirement is in the [Soniox manual finalization documentation](https://soniox.com/docs/stt/rt/manual-finalization): send `finalize` only after approximately **200 ms of silence following speech end**. Sending it earlier can degrade recognition accuracy.

For Vachanam this should be implemented, if tested later, as a cancellable timer:

```text
local VAD reports end of speech
        |
        +-- start 200 ms timer
                |
                +-- speech resumes -> cancel; do not finalize
                |
                +-- silence continues -> send one finalize message
```

This is not the same as the reverted immediate-finalize experiment. It preserves trailing acoustic context and follows the vendor's stated accuracy/latency balance.

### LiveKit version gap and documentation mismatch

There are three separate facts that must not be conflated:

- The running local/production package inspected during the latency investigation was `livekit-plugins-soniox==1.6.5`. Its `STTOptions` has `max_endpoint_delay_ms` and `endpoint_sensitivity`, defaults the maximum to 2000 ms, and does not contain `endpoint_latency_adjustment_level`.
- The repository now pins `livekit-plugins-soniox==1.6.6` in `agent/livekit_minimal/requirements.txt`. The [official LiveKit 1.6.6 release](https://github.com/livekit/agents/releases/tag/livekit-agents%401.6.6) explicitly says it adds the Soniox endpoint-latency-adjustment parameter.
- Soniox's current [LiveKit integration page](https://soniox.com/docs/integrations/livekit/stt) lists `max_endpoint_delay_ms` with a default of 500 ms, while both the Soniox WebSocket API and the inspected LiveKit Python reference show 2000 ms. The deployed package/source must be treated as authoritative for Vachanam; a web page default must not be assumed to be active.

The next deployment should log the installed package version and the effective Soniox options once at worker startup. Otherwise a requirements-file change can be mistaken for a production behavior change.

### Region

Vachanam has already moved its Soniox connection to the Japanese regional WebSocket and previously measured a much shorter network connection time from the Mumbai Fly machine than the US/EU endpoints. There is no obvious remaining Soniox region change to recover another large latency saving. Endpoint decision time, not geography, is now the Soniox-side target.

## Why the earlier experiment failed to prove the broader claim

The previous result proves one narrow fact:

> Immediate forced finalization plus an 800 ms maximum and sensitivity 0.3 was unacceptable for the tested Telugu call.

It does not prove any of the following:

- that `endpoint_latency_adjustment_level=1` harms Telugu;
- that a 200 ms delayed manual finalize harms Telugu;
- that a 1000–1500 ms tail cap harms Telugu;
- that sensitivity 0.3 alone caused the observed name error;
- that manual finalize alone caused the observed fragmentation.

The name substitution and chopped utterances are consistent with premature finalization, but the combined experiment does not allow causal attribution. The correct response is a controlled A/B, not another combined tuning patch.

## Proposed Soniox experiment matrix

No experiment should be promoted based on one live conversation. Use recorded, consented, de-identified telephony audio replayed in real time, followed by a small guarded live-call canary.

| Arm | Change from current baseline | Purpose |
|---|---|---|
| S0 | None | Re-establish baseline on the exact same corpus/build |
| S1 | `endpoint_latency_adjustment_level=1` only | Test the mild semantic low-latency profile |
| S2 | `endpoint_latency_adjustment_level=2` only | Test the next profile if S1 passes accuracy |
| S3 | Cancellable finalize after 200 ms silence only | Test vendor-recommended client finalization independently |
| S4 | `max_endpoint_delay_ms=1500` only | Test a conservative tail cap |
| S5 | `max_endpoint_delay_ms=1000` only | Test a stricter tail cap only if S4 passes |
| S6 | Best passing latency level + best passing delayed-finalize/cap | Test interaction only after causal effects are known |

Do not begin with sensitivity 0.3. If S1/S2 improve latency but miss the target, test sensitivity in small increments such as 0.1 and 0.2 as separate arms.

### Required measurements

Measure these at p50, p95 and p99, not just averages:

- physical speech-end to Soniox `<end>`/`<fin>`;
- physical speech-end to LiveKit committed user turn;
- word error rate (WER);
- medical/booking entity error rate: patient name, doctor, date, time, phone and treatment;
- premature endpoint rate per 100 turns;
- fragmented multi-segment turn rate;
- false turn commits caused by thinking pauses;
- code-mixed Telugu-English accuracy;
- 8 kHz telephone audio separately from clean 16 kHz audio.

### Promotion gate

A reasonable initial gate is:

- at least 200 representative turns, including short acknowledgements and long hesitant requests;
- no statistically meaningful deterioration in entity accuracy;
- no increase greater than 0.5 percentage points in absolute WER without an explicit product decision;
- premature/false commit rate below 1% of turns;
- endpoint p50 at or below 400 ms and p95 at or below 700 ms;
- no regression in interruption or backchannel behavior.

These are Vachanam engineering acceptance targets, not Soniox guarantees.

## Market alternatives for fast Telugu results

Vendor latency numbers below are **not directly comparable**. Some vendors report time to first partial transcript (TTFT), while Vachanam's user-visible delay depends on final/committed end-of-turn. Deepgram itself warns that transcript latency and end-of-turn latency are different measurements. Every shortlisted provider must be replayed against the same audio and measured from physical speech end to safe LLM start.

| Provider/model | Telugu status | Published speed/endpoint controls | Vachanam fit | Main risk | Verdict |
|---|---|---|---|---|---|
| **Soniox stt-rt-v5** | Supported; current accuracy winner in Vachanam | Semantic adjustment levels 0–3, sensitivity, 500–3000 ms cap, manual finalize after ~200 ms silence | Already integrated, context terms and regional endpoint in place | Aggressive endpointing can split speech or lower accuracy | **Tune first** |
| **Sarvam Saaras v3** | `te-IN`; designed for Indian languages | High VAD sensitivity uses a 0.5 s silence boundary; explicit flush for immediate processing; fine-grained VAD; 8 kHz PCM support | Already implemented as Vachanam fallback, so lowest engineering effort | Previous Vachanam experience favored Soniox accuracy; public claims are not a current Vachanam benchmark | **A/B first among alternatives** |
| **Smallest Pulse** | Telugu Beta, India region; also South-Indic+English aggregator | Vendor reports about 150 ms TTFT at one concurrent stream and ~300 ms at 100; endpointing on by default; explicit finalize and end-of-utterance ceiling | India endpoint; Vachanam already uses Smallest for TTS/account relationship | Telugu streaming support is very new and explicitly Beta; TTFT is not final-turn latency | **High-upside experimental A/B** |
| **Deepgram Nova-3** | Telugu added/supported as `te` | Vendor reports sub-300 ms streaming transcription; silence endpoint is configurable, e.g. 300 ms; keyterm prompting available | Mature streaming API and clear latency measurement tooling | Nova-3 endpointing is VAD/silence based, not Flux's integrated semantic EOT; Telugu support is new | **Strong speed A/B** |
| **ElevenLabs Scribe v2 Realtime** | Telugu supported; vendor classifies it in its >5% to <=10% WER band | Vendor advertises ~150 ms realtime latency; manual commit or VAD; VAD minimum speech/silence controls down to 100 ms; 8 kHz PCM and mu-law | Good telephony formats and explicit commit control | Docs say processing starts after first 2 s of audio; ~150 ms is not a guaranteed final-turn measure; new integration needed | **Benchmark, do not assume** |
| **Google Chirp 3** | `te-IN` is Preview | Streaming plus STANDARD/SHORT/SUPERSHORT endpoint sensitivity | Strong platform and explicit low-latency modes | Telugu is Preview; current documented Chirp 3 availability is US/EU, adding distance from Mumbai; SUPERSHORT is intended for very short commands | **Secondary experiment** |
| **Azure Speech** | `te-IN` realtime supported | Silence segmentation can be set to 300 ms | Mature SDK and explicit silence threshold | No Telugu-specific end-of-turn latency published; semantic segmentation is not recommended for interactive scenarios and is not available for every language | **Lower-priority benchmark** |
| **AWS Transcribe** | `te-IN` streaming supported | Partial-result stabilization offers low/medium/high speed-accuracy trade-offs | Mature infrastructure and stable partial-word flags | No strong numeric Telugu end-of-turn claim; fewer endpoint controls for this use case | **Lower-priority benchmark** |
| **AssemblyAI Whisper Streaming** | Telugu supported through `whisper-rt` | Partial and finalized turns over WebSocket | Broad language coverage | It relies on automatic language detection and does not expose the same proven Telugu/entity path; AssemblyAI's fastest semantic voice-agent models support only six major languages, not Telugu | **Not in the first round** |

### Sources and interpretation by provider

#### Sarvam Saaras v3

Sarvam's [streaming STT documentation](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api) provides the most relevant facts: Saaras v3 supports WebSocket streaming, `high_vad_sensitivity`, speech start/end events, manual flush, 8 kHz telephony configuration, and low-level VAD thresholds. Its high-sensitivity preset uses a 0.5-second silence boundary rather than one second. The public [Sarvam STT page](https://www.sarvam.ai/speech-to-text) says the model covers all scheduled Indian languages, code mixing and 8 kHz telephony, but those are vendor claims and must be retested on Vachanam audio.

Sarvam is the quickest provider experiment because `_build_stt` already constructs Saaras v3 with `flush_signal=True` whenever the Soniox key is absent. A controlled provider flag is safer than removing a credential to force fallback.

#### Smallest Pulse

The [Pulse model card](https://docs.smallest.ai/waves/model-cards/speech-to-text/pulse) lists Telugu streaming as Beta on the India endpoint and reports approximately 150 ms streaming TTFT at one concurrency and approximately 300 ms at 100 concurrency. Its [endpointing documentation](https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/features/endpointing) says finalize-on-silence is on by default, a client `finalize` message takes precedence, and an end-of-utterance timeout can act as a ceiling.

This is promising for network locality and provider consolidation with Vachanam's existing Smallest TTS. It is not yet a safe default because Telugu support was added only recently and remains Beta. Test names, code mixing, quiet speakers and 8 kHz carrier audio aggressively.

#### Deepgram Nova-3 and Flux

Deepgram's [latency guide](https://developers.deepgram.com/docs/measuring-streaming-latency) reports sub-300 ms streaming latency for Nova-3 and distinguishes transcript latency from end-of-turn latency. Its [endpointing documentation](https://developers.deepgram.com/docs/endpointing) allows the silence duration to be configured, and its [model/language matrix](https://developers.deepgram.com/docs/models-languages-overview/) includes Telugu in Nova-3.

Flux should not be proposed for Vachanam Telugu today. Although it is Deepgram's voice-agent model with integrated EOT and eager EOT, the [official Flux language list](https://developers.deepgram.com/docs/flux/language-prompting) supports English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian and Dutch—not Telugu. Nova-3 is the valid Deepgram candidate, but it requires separate endpointing.

#### ElevenLabs Scribe v2 Realtime

The [ElevenLabs STT overview](https://elevenlabs.io/docs/overview/capabilities/speech-to-text/) lists Telugu support, places its published Telugu benchmark in the >5% to <=10% WER band, and advertises approximately 150 ms latency for Scribe v2 Realtime. The [commit-strategy guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies) documents manual and VAD commit, 100 ms minimum speech/silence controls, and 8 kHz PCM/mu-law input.

The same guide says transcript processing begins after the first two seconds of audio. This does not necessarily add two seconds after speech ends, but it is a test risk for very short replies such as “yes,” “no,” names and times. The vendor's 150 ms number should be treated as partial-transcription latency until a speech-end-to-commit benchmark proves otherwise.

#### Google, Azure and AWS

- [Google Chirp 3](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3) supports streaming Telugu in Preview and exposes SHORT/SUPERSHORT endpoint sensitivity. SUPERSHORT is designed for single words and commands, not normal hesitant clinic conversation. Current documented regions are US and EU.
- [Azure's language table](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support) includes realtime `te-IN`; its [recognition guide](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech) shows a 300 ms silence segmentation setting. Azure also says semantic segmentation should not be used for interactive scenarios and is not supported for all locales.
- [AWS's language matrix](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html) includes Telugu streaming, and [partial-result stabilization](https://docs.aws.amazon.com/transcribe/latest/dg/streaming-partial-results.html) can trade some accuracy for faster stable partials. AWS does not publish a directly useful Telugu end-of-turn guarantee.

## Recommended provider bake-off

Use the same corpus and wall-clock playback harness for every provider. Do not compare dashboard demos or each vendor's preferred sample file.

### Round 1

1. Soniox 1.6.6 baseline and isolated latency-adjustment arms.
2. Sarvam Saaras v3 with the current LiveKit integration and manual flush.
3. Smallest Pulse on the India WebSocket.
4. Deepgram Nova-3 with endpointing at 300 ms and 500 ms as separate arms.
5. ElevenLabs Scribe v2 Realtime with manual commit after the same 200/300 ms client silence used in the other arms.

### Corpus composition

At minimum include:

- 100 native Telugu booking utterances;
- 50 Telugu-English code-mixed utterances;
- 25 names from the actual doctor/patient name distribution;
- 25 dates, times, phone numbers and token numbers;
- quiet/elderly/hesitant speakers with mid-sentence pauses;
- common backchannels and interruptions;
- both clean 16 kHz and actual 8 kHz telephone-path recordings;
- carrier noise, packet loss and overlapping agent/caller audio.

### Scoring

Use a two-dimensional gate; never select the minimum latency alone.

```text
eligible provider = entity accuracy passes AND false-commit rate passes
winner among eligible providers = lowest speech-end-to-safe-commit p50/p95
```

For Vachanam, entity error rate matters more than generic WER. Transcribing a filler incorrectly is annoying; transcribing the wrong patient, doctor, time or phone number breaks the clinic workflow.

## Final recommendation

Do not replace Soniox yet. First exploit the control that the currently running 1.6.5 plugin did not expose: deploy and verify LiveKit Soniox 1.6.6, then A/B `endpoint_latency_adjustment_level=1` and `2` one at a time. In parallel, test a 200 ms delayed and cancellable manual finalize. This is the smallest change surface and preserves the provider that has already won Vachanam's accuracy comparison.

If Soniox cannot reach approximately 400 ms p50 / 700 ms p95 without failing entity accuracy, run the provider bake-off. Sarvam is the quickest integration result, Smallest Pulse is the most interesting India-local new entrant, and Deepgram Nova-3 has the clearest mature latency tooling. Keep ElevenLabs in the same benchmark, but do not interpret its 150 ms marketing number as committed-turn latency.

Finally, treat STT as only one part of the sub-second goal. With Vachanam's measured 0.80–1.40 second Gemini first-token time and no observed prompt caching, a faster STT provider alone cannot produce a complete response in under one second. The sub-second plan needs both a roughly 300 ms STT commit and a roughly 300 ms first speakable LLM fragment, with streaming TTS beginning immediately after that fragment.
