# Vachanam — Competitive Benchmarks

*Compiled 2026-08-09. Our numbers are measured from production and sandbox
telemetry. Competitor numbers are third-party or vendor-published and are
labelled as such. Read §1 before reading any table — the measurement
methodologies are not the same, and pretending otherwise is how vendors lie
about latency.*

---

## 1. The measurement problem, stated first

There is **no independently verified study that measures every voice-agent
platform across every latency layer**. Published figures measure different
sections of the call path, use different models, and disclose different levels
of methodology.

Two measurement points matter and they differ by a large constant:

| Measured | What it captures | Who reports it |
|---|---|---|
| **Server-side** | Last recognised word → response audio queued for send | Almost every vendor, and our own `lat:turns` |
| **Ear-side** | Caller stops speaking → agent audio actually audible in the call recording | The Openbenchmarks study; what a clinic owner's stopwatch measures |

The Openbenchmarks study found that **platform-reported figures read roughly
490 ms lower than caller-experienced latency**, because server-side numbers
exclude the carrier legs, jitter buffering and playout.

**Our numbers in this document are server-side.** They are the floor of what a
caller hears, not what they hear. Any comparison against ear-side figures must
add roughly 490 ms to ours, and where that changes the conclusion, this
document says so rather than quietly benefiting from the gap.

---

## 2. Our measured numbers

Both from Redis `lat:turns`, real PSTN calls in Telugu, one line per caller
turn.

### Production stack — Soniox TTS

Session `8191709e`, 21 turns, 2026-08-09:

| | ms |
|---|---|
| p50 | 1,713 |
| p95 | 2,222 |
| max | 2,222 |

### Sandbox stack — Cartesia `sonic-3` TTS

Session `ee2b1c96`, 10 turns, prompt cache hitting on every turn:

| | `total_ms` | `from_last_word_ms` (felt) |
|---|---|---|
| min | 521 | 632 |
| **p50** | **1,392** | **1,470** |
| max | 1,556 | 1,571 |

Three earlier sandbox sessions, all with the prompt cache **missing**, for
context: p50 1,548 / 1,810 / 2,062 ms.

### Where the time goes — the two stacks side by side

| Stage | Production (Soniox TTS) | Sandbox (Cartesia TTS) |
|---|---|---|
| Speech recognition finalise | 375–455 ms | 383–456 ms |
| Language model, first token (cached) | 420–580 ms | 410–473 ms |
| **Speech synthesis, first audio** | **~510 ms** | **89–105 ms** |

**Swapping the synthesiser removed roughly 420 ms from every single turn.**
That is the whole story of the sandbox result. Speech recognition, not
synthesis, is now the dominant stage.

---

## 3. Against generic voice-agent platforms

### The one credible third-party study

Openbenchmarks (2026) dialled five platforms over **real phone calls** with a
caller robot, a fixed script, both sides recorded on one clock, endpointing
standardised to 0.1 s where configurable. **2,078 usable turns.** Ear-side
measurement, not platform-reported.

| Platform | p50 (ear-side) | p95 | p95 ÷ p50 |
|---|---|---|---|
| Telnyx | 1,296 ms | 1,856 ms | 1.43 |
| ElevenLabs | 1,424 ms | 1,768 ms | 1.24 |
| Bland AI | 1,520 ms | 2,248 ms | 1.48 |
| Vapi | 1,558 ms | 2,008 ms | 1.29 |
| Retell AI | 1,740 ms | 2,259 ms | 1.30 |
| — | | | |
| **Vachanam sandbox** *(server-side)* | **1,470 ms** | **1,571 ms** | **1.07** |
| **Vachanam sandbox** *(ear-side, +490 ms est.)* | **~1,960 ms** | **~2,060 ms** | 1.05 |

### Reading this honestly

**On raw median latency we are not ahead.** Corrected to ear-side, our ~1,960 ms
estimate sits behind all five platforms measured. Anyone claiming otherwise is
comparing our server-side number to their ear-side number, and that is a 490 ms
lie.

Three things make the comparison less unfavourable than it looks, and they are
mitigations, not refutations:

1. **They tested English on US infrastructure. We are running Telugu over Indian PSTN.** Telugu endpoint detection is intrinsically slower — the recogniser has to wait longer to be confident an utterance ended — and Indian carrier legs are longer.
2. **Their script was a greeting, scripted questions, and a goodbye. No tool calls.** Our turns include live database reads, availability resolution and real bookings. A turn that books an appointment is doing strictly more work than a turn that answers a scripted question.
3. **Their endpointing was standardised to 0.1 s.** Our sandbox runs 0.06 s, so this one cuts in our favour and is already reflected in our number.

### Where we genuinely lead: the tail

**Our p95 is 1.07× our p50. The best platform measured is 1.24×; the worst is 1.48×.**

This is the metric the study itself calls critical: *"turns exceeding ~2 seconds
of silence prompt callers to assume dropped calls and speak over agents."* A
platform with a 1,520 ms median and a 2,248 ms p95 sounds fine on average and
breaks the conversation once every twenty turns. On a twenty-turn booking call
that is once per call.

Our worst sandbox turn was **1,571 ms**. Not one turn crossed the 2-second
threshold where callers start talking over the agent.

> **Caveat that must travel with this claim: n = 9 turns, one call.** Their
> figure is ~420 turns per platform. Our tail ratio is a promising signal, not
> a proven property, and the honest next step is a ≥30-turn corpus before it
> goes in a deck. Until then it is stated as "measured on one call", never as
> "we are more consistent than Vapi."

### The architectural point that matters more

Telnyx, Vapi, Bland, Retell and ElevenLabs sell **toolkits**. The study's own
conclusion is that *"the platform is not your latency — the same engine lands
anywhere from ~560 ms to ~810 ms p50 depending on how the loop, tools, and
streaming are built."*

That cuts both ways, and it is the honest frame: latency is an engineering
outcome, not a vendor choice. It means our number is ours to improve — and it
means none of those platforms is a competitor to a clinic, because a clinic
cannot buy a toolkit and have a receptionist. It would still need Indian
telephony, Telugu that survives a noisy line, doctor schedules with split
shifts and leave, a token queue, calendar integration, atomic booking, and DPDP
posture. **We compete with what someone would build on top of them, not with
them.**

---

## 4. Against the components

Our synthesis measurement lines up with published third-party figures, which is
a useful sanity check that our telemetry is not flattering us:

| Source | Cartesia Sonic-3 time-to-first-audio |
|---|---|
| Vendor claim (Turbo) | ~40 ms |
| Vendor claim (standard) | ~90 ms |
| Coval independent benchmark | 188 ms p50, 100 ms interquartile range |
| **Our measurement, in-call, Telugu, Mumbai→Cartesia** | **89–105 ms** |

We land at the vendor's standard-model claim and **better than the independent
benchmark**, which is plausible rather than suspicious: our worker is in Mumbai
on a warmed persistent WebSocket, and we synthesise short first sentences
deliberately.

One caution the independent benchmark raises and we have already observed:
**Sonic-3's latency spread is wide.** In our own best session, synthesis
first-audio was 89–105 ms on turns 1–4 and 317–353 ms on turns 5–10 — something
stops reusing the warm connection partway through a call. Fixing that would
take roughly another 230 ms off the median, landing p50 near **1,150–1,250 ms**
server-side. That is an open engineering item, not a claim.

---

## 5. Against the alternative architecture

| Architecture | First-audio latency | Trade-off |
|---|---|---|
| Cascaded (ours): speech → text → model → text → speech | 300–600 ms best case for the stack; **realistic floor 800–1,000 ms** with real tool calls | Full control of each stage; can swap any vendor; tool calls are natural |
| Native speech-to-speech (GPT Realtime, Gemini Live) | **300–600 ms** target, 200–300 ms claimed best case | Roughly double the variable cost; Telugu quality unproven; tool calling and deterministic guardrails harder |

The pre-2026 conventional wisdom was that cascaded stacks run 1.5–8 s. Our
1.4 s with real bookings is at the good end of that range, and the Cartesia
result shows the cascade has more headroom than we credited it with two days
ago. **The strategic conclusion has changed:** we previously wrote that
sub-second requires speech-to-speech. With synthesis at ~90 ms, the remaining
cost is speech recognition finalisation, and sub-second on the cascade is now
plausible. Speech-to-speech moves from "the only path" to "one option, and the
expensive one."

---

## 6. Against Indian-market competitors

This is the comparison that decides deals, and it is the one with the least
reliable public data. Everything below is vendor-published or press-published;
none of it is independently measured, and none of these vendors publishes
latency the way Openbenchmarks measures it.

| | Vachanam | Indian voice-AI market (published) |
|---|---|---|
| **Entry price** | **₹1,999/mo** incl. 150 min and a phone number | Platform subscriptions typically from ₹2,999/mo; minimum commitments commonly ₹3,000–5,000/mo |
| **Per-minute** | **₹5/min** overage; effective ₹6.67/min all-in on the ₹9,999 plan | ₹2–12/min all-in; Indian street pricing commonly ₹4–9/min |
| **High end** | ₹17,999/mo, 3,000 min | VaniAgent ₹21,999/mo unlimited calls |
| **Languages** | 8, one validated in depth | HuskyVoice claims 30+; Reverie 12+ Indian languages |
| **Positioning** | Clinic-specific application | Mostly horizontal platforms with a healthcare page |
| **Case studies** | **None** | Caller Digital publishes a no-show reduction of 32% → 12% |
| **Certifications** | **None** (infrastructure vendors are SOC 2 / ISO certified) | Enterprise vendors (Kore.ai) carry certifications |

### Where we are ahead

**1. Price floor.** ₹1,999 including a phone number and 150 minutes sits below
the market's typical ₹3,000–5,000 minimum commitment. For a clinic weighing
this against a receptionist's salary, being the cheapest credible yes matters
more than being the fastest.

**2. Per-minute at the low end of the range.** ₹5/min against a ₹4–9/min street
range, with the number and platform included rather than billed separately.

**3. Depth over breadth in language.** Competitors advertise 30+ languages. We
advertise 8 and have driven exactly one to the point where callers interrupt
it, switch languages mid-sentence, mix English into Telugu, and it holds. A
clinic in Hyderabad does not need 30 languages; it needs one that does not
embarrass them. **Breadth is a marketing number; depth is what survives a real
call.**

**4. It is an application, not a platform.** Doctor schedules with split
shifts, exact-date publishing, leave that cascades into rebooking calls, token
queues versus timed appointments, calendar writes inside the booking
transaction, atomic token assignment. A horizontal platform sells the ability
to build this. We have built it.

**5. Booking correctness as a guarantee.** Token numbers from an atomic counter
plus a per-slot database lock, proven by a test that races N simultaneous
callers at one slot and asserts exactly one wins. No horizontal platform offers
this, because it is not their layer — it is the clinic's problem to solve, and
most integrations solve it by counting rows, which double-books under load.

**6. Data posture.** We refuse to be an EMR. Name, phone, one complaint line,
token. No recordings. Clinic stays Data Fiduciary; we are the Processor with a
published DPA offered to every clinic, not just enterprise. Competitors holding
records carry a bigger honeypot and a longer procurement conversation.

**7. The follow-up loop.** The doctor writes a note and a question; the AI rings
the patient days later, asks it, relays the answer, books the next visit. This
is retention revenue for the clinic, and we include it on every paid plan
because it generates metered minutes rather than costing us anything. Most
scheduling tools stop at the booking.

### Where we are behind, and should say so

1. **Raw ear-side latency** against the best generic platforms — see §3.
2. **Zero customers, zero case studies.** Caller Digital publishes an outcome number. We cannot publish any outcome, because we have never run in a clinic.
3. **No organisational certification.** We must say *"runs entirely on SOC 2 / ISO-certified infrastructure"* and never imply we hold ISO 27001 ourselves.
4. **Language breadth.** Eight against thirty-plus. We should argue depth, not match the number.
5. **Single point of failure.** One agent machine. Enterprise competitors have redundancy we do not.

---

## 7. The defensible summary

**What we can say in a room, and defend under questioning:**

> On our sandbox stack we measure a 1,392 ms median turn, server-side, on real
> Telugu phone calls that include live database lookups and real bookings — with
> a p95 of 1,571 ms. The independent Openbenchmarks study of five major
> platforms found ear-side medians from 1,296 to 1,740 ms with p95 tails from
> 1.24× to 1.48× the median. Our tail ratio measured 1.07× on one call. We are
> not claiming to be the fastest — corrected to ear-side we are not — we are
> claiming to be **consistent**, in a language none of them handle, doing work
> none of them do, at a price below the Indian market's typical minimum
> commitment.

**What we must never say:**

- That we beat Vapi or Retell on latency. Not on an equal measurement.
- That our tail ratio is proven. n = 9 turns.
- That we hold any certification.
- Any outcome number for a clinic. We have no clinics.

---

## 8. What would settle the argument

The cheap experiment that turns most of this document from argument into
evidence:

1. **A ≥30-turn Telugu corpus on the sandbox stack**, so the p50 and the tail ratio stop being one call.
2. **One ear-side measurement** — record the caller side of a sandbox call and measure last-word to first-audio in the recording. That converts our server-side number into the same units the rest of the industry publishes, and removes the 490 ms argument permanently. It costs one phone call and an audio editor.
3. **Fix the synthesis connection reuse** (§4). Worth ~230 ms.
4. **One pilot clinic's before/after missed-call rate.** This is the only number that makes any of the rest of it matter.

---

## Sources

- [Voice AI platform end-to-end latency comparison (2026) — per-turn TTFAB benchmark, 5 voice agents — Openbenchmarks](https://openbenchmarks.com/voice-agent-latency/voice-agent-end-to-end-latency)
- [Voice AI agents compared on latency: performance benchmark — Telnyx](https://telnyx.com/resources/voice-ai-agents-compared-latency)
- [Voice AI Latency Benchmarks: What Agencies Need to Know in 2026 — Trillet](https://trillet.ai/blogs/voice-ai-latency-benchmarks)
- [2026 AI Voice Agent Benchmark: Latency & Cost per Minute — DestiLabs](https://www.destilabs.com/blog/ai-voice-agent-benchmark-2026)
- [Retell vs Vapi vs Bland: We Built on All 3 (2026) — TECHSY](https://techsy.io/en/blog/retell-ai-vs-vapi-vs-bland)
- [TTS Latency Benchmark 2026: TTFA Compared Across Gradium, ElevenLabs, Cartesia and Deepgram — Gradium](https://gradium.ai/content/tts-latency-benchmark-2026)
- [Cartesia AI Review 2026: The Fastest TTS Tested — TextToLab](https://texttolab.com/blog/cartesia-ai-review)
- [7 Best TTS APIs for AI Voice Agents in 2026 (Tested & Ranked) — Cekura](https://www.cekura.ai/blogs/best-tts-for-ai-voice-agents)
- [Best Speech-to-Speech AI APIs for Realtime Apps (2026) — Inworld](https://inworld.ai/resources/best-speech-to-speech)
- [Gemini 3.1 Flash Live vs GPT Realtime 1.5 — Flowtivity](https://flowtivity.ai/blog/gemini-3-1-flash-live-vs-gpt-realtime-1-5-voice-agent-comparison-2026/)
- [Voice AI Agent Cost in India 2026: Per-Minute & Monthly Pricing — Ravan.ai](https://www.ravan.ai/blog/voice-ai-agent-cost-india-2026)
- [Voice AI Pricing in India Per Minute: Real Costs — Caller Digital](https://caller.digital/voice-ai-pricing-india)
- [AI Voice Agent for Hospital Appointment Booking India — Caller Digital](https://caller.digital/blog/ai-voice-agent-hospital-appointment-booking-india)
- [AI Receptionist Pricing: Cost Guide for Business Calls — HuskyVoiceAI](https://www.huskyvoice.ai/ai-receptionist-pricing)
- [VaniAgent — Unlimited AI Calling from Rs 21,999/month](https://vaniagent.com/)
- [Top 10 Voice AI Agents in India: Features, Pricing & Comparison for 2026 — MyOperator](https://myoperator.com/blog/top-10-voice-ai-agents-india-2026)
- [Best AI Receptionist for Clinics in India (2026) — ConnectAI](https://www.connectai.care/learn/best-ai-receptionist-for-clinics-india)
