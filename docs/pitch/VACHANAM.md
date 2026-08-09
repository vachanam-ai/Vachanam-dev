# Vachanam

**AI receptionist for Indian clinics. Answers the phone in the patient's own language, books the appointment, and never double-books.**

*Healing starts with being heard.*

---

**Document status.** Written 2026-08-09 by reading the codebase, not by
summarising the older documents. Every quantitative claim is either (a) read
directly out of source code, (b) measured from production telemetry, or (c)
explicitly labelled as an unvalidated estimate. Where an older document in this
repository contradicts this one, that document is wrong and is listed in §19.

**Company.** Vachanam · Founder: Vinay Rongala · Hyderabad, India ·
vachanam.in · hello@vachanam.in

---

## Contents

1. The one-paragraph version
2. The problem
3. The unique selling proposition
4. Why now
5. What the product does today
6. How it is built
7. Technical benchmarks
8. Competitive benchmark
9. Brand positioning
10. Ideal customer and market
11. Business model and unit economics
12. Go-to-market
13. Engineering reality
14. Data protection and regulatory position
15. Traction, stated plainly
16. Metrics that will decide this business
17. Risks
18. Where it goes, and what capital is for
19. Corrections to older documents
20. How to verify any claim here

---

## 1. The one-paragraph version

An Indian clinic's phone rings 20–80 times a day. One receptionist answers,
writes in a paper register, and cannot pick up while she is already on a call
or walking a file to a doctor. Every unanswered ring is a patient who calls the
next clinic. Vachanam replaces that lost capacity: the clinic forwards its
existing number to us, and an AI receptionist answers every call in Telugu,
Hindi, Tamil, Kannada, Malayalam, Marathi, Bengali or English, understands why
the patient is calling, picks the right doctor, checks that doctor's real
published hours, assigns a token atomically, confirms out loud, writes a Google
Calendar event, and messages the patient on WhatsApp. Clinic staff mark
attendance on a phone; the owner sees where the calls went. We charge a monthly
subscription plus per-minute overage. The software is built and running in
production. We have **no paying clinics yet** — that is the next milestone, not
a past one.

---

## 2. The problem

**The observable fact:** in Indian outpatient clinics, appointment intake is a
single-threaded human process. One receptionist, one phone line, a paper
register. The system has no queue — a call arriving while she is busy is simply
lost, and neither the clinic nor the patient ever learns it happened.

**Why it persists.** Existing scheduling software asks the *patient* to change
behaviour: install an app, use a website, create an account. Indian patients —
especially outside metros, especially over 40 — call. Any solution depending on
the patient acting differently does not get adopted. And any solution depending
on the *clinic* acting differently — retraining staff, migrating records — gets
abandoned in week two.

**Our sizing estimate, and its status.** The working estimate behind this
company: clinics miss 20–30% of inbound calls at peak, and each missed call is
a lost consultation worth ₹300–500, so ten missed calls a day is ₹3,000–5,000
of daily lost revenue.

> **This estimate is not yet validated.** It comes from founder conversations
> with Hyderabad clinics, not from instrumented measurement. We have never
> measured a real clinic's missed-call rate, because we have never run in a real
> clinic. Validating it is the single most valuable output of the first pilot —
> and Vachanam is itself the instrument, since every answered call is logged. An
> investor should treat the market arithmetic as a hypothesis this product is
> designed to test cheaply, not as a finding.

---

## 3. The unique selling proposition

**One sentence:** *Vachanam is the only appointment system that requires no
behaviour change from the patient, no behaviour change from the doctor, and no
migration of clinical records — because it answers the phone that already
rings.*

Five things, together, are hard to assemble and are what we actually sell:

**1. Zero patient adoption cost.** The patient dials the number on the clinic's
board, the same number they have always dialled. No app, no link, no account,
no literacy or smartphone assumption. Every competitor that routes through an
app pays an adoption tax on the least tech-forward half of the market. We pay
none.

**2. The patient's own language, spoken naturally.** Not IVR menus, not "press
1 for appointments" — conversation. Eight languages, with Telugu validated on
live PSTN calls to the point where callers argue with it, interrupt it, switch
languages mid-sentence, and mix English words into Telugu, and it holds. This
is the hardest part to copy and the part a demo call sells instantly.

**3. Booking correctness as an architectural guarantee, not a feature.** Token
numbers come from an atomic counter, never a row count. Slot capacity is
additionally protected by a per-slot database lock. A held token dies with its
call. The calendar write is part of the booking; a notification failure never
is. A clinic that gets double-booked once stops trusting the software forever —
so this is treated as the product's load-bearing wall, and there is a
concurrency test that races N simultaneous callers at one slot and asserts
exactly one wins.

**4. It calls back — the retention loop.** Most scheduling tools stop at the
booking. Vachanam rings the patient 24 hours ahead and 30 minutes ahead, rings
patients whose doctor took leave to rebook them, and — this is the differentiated
one — runs a **treatment follow-up loop**: the doctor writes a one-line note
and a question, the AI rings the patient days later, asks it, relays the answer
back, and books or moves the next visit. That converts a one-time consultation
into a returning patient, which is the clinic's actual economics. It is included
on every paid plan because it generates metered minutes rather than costing us
anything.

**5. Deliberately not an EMR.** We refuse to store medical records, diagnoses,
prescriptions, test results or government identifiers. This is a competitive
weapon, not a limitation: it removes the year-long procurement conversation, it
removes the migration project, it removes the honeypot that makes a breach
catastrophic, and it lets a clinic keep its existing software untouched. The
sales objection "we already have clinic software" has an answer: *good — keep
it. That software doesn't answer your phone.*

**What we do not claim.** We are not a patent moat. Voice models are
commoditising and will keep commoditising. Our defence is the assembly —
Indian telephony, Indian-language quality, the clinic queue/token model,
doctor schedules with split shifts and leave, calendar, DPDP posture — plus
the switching cost of a clinic's phone number and schedule living here, plus
speed to a clinic network.

---

## 4. Why now

- **Indian-language speech recognition crossed the usability line recently.** Conversational Telugu over a noisy PSTN line was not commercially viable two years ago. It is now.
- **Language models became fast and cheap enough to sit inside a phone call.** A cached clinic prompt costs a fraction of a rupee per turn.
- **India got a real data-protection law.** The DPDP Act 2023 makes "where does patient data live and who can read it" a board-level question for clinics. A vendor with a genuine answer, and a data footprint small enough to defend, is newly advantaged.
- **WhatsApp became the default business channel in India**, and Meta opened a Tech Provider path that lets each clinic own its own account rather than renting ours.
- **The receptionist salary did not get cheaper.** Our entry plan is ₹1,999/month against a full-time salary; the comparison is not subtle.

---

## 5. What the product does today

Everything here is implemented and running in production unless the line says
otherwise.

### 5.1 The voice agent

| Capability | Notes |
|---|---|
| **Answers in 8 languages** | Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi, Bengali, English. Telugu is the reference implementation and the only one validated at length on real calls. |
| **Switches language mid-call** | On explicit request, re-stating its previous answer in the new language rather than restarting. |
| **Routes to the right doctor** | From the patient's own words. No medical judgment — it matches to a stated specialty, it does not triage. |
| **Reads real availability** | Per-doctor, per-date, honouring published sessions, split shifts, exact-date overrides and leave. Missing data fails closed: it says the timing is not published rather than guessing. |
| **Books atomically** | Redis `INCR` plus a per-slot Postgres advisory lock. |
| **Reschedules** | Moves the existing booking. Cannot leave a patient holding two — the replacement must be confirmed before the original is released. |
| **Cancels** | Frees the slot, deletes the calendar event. Requires explicit caller authorisation, recognised in native script, Latin transliteration and English. |
| **Finds the caller's bookings** | Matched on verified inbound caller ID, never a number spoken aloud. |
| **Reports queue position** | For token-queue doctors. |
| **Takes a message for the doctor** | When the request exceeds what it can do. |
| **Logs an unanswerable question** | Routed to the doctor, who answers in the dashboard; the patient gets an automatic callback. |
| **Hands off to a human** | On explicit request or persistent intent, surfacing the clinic's own emergency contact. |

16 callable tools. The agent gives no medical advice, no diagnosis, no triage
classification, and never refers a caller to emergency services. These are hard
product constraints, not model instructions.

### 5.2 Outbound calls

- **30-minute pre-appointment reminder** — confirms attendance or moves the visit
- **24-hour day-before reminder** — only for bookings made ≥24h ahead
- **Treatment follow-up** — the retention loop described in §3
- **Cascade rebook** — when a doctor takes leave, affected patients are called and offered new slots
- **Question callback** — the caller gets rung back with the doctor's answer

All outbound dialling passes one guard, so two jobs due in the same minute
cannot ring the same patient twice.

### 5.3 WhatsApp

Vachanam is registered with Meta as an independent **Tech Provider**. Each
clinic owns its own WhatsApp Business Account and pays Meta directly — we never
resell messaging, which keeps Meta off our sub-processor list and off our
balance sheet. Built and running:

- Inbound webhook, HMAC-verified, idempotent, tenant resolved from the *receiving* number
- An AI agent on WhatsApp that answers, books, reschedules and cancels
- Clinic FAQ grounding, which outranks the doctor roster when they disagree
- Confirmations, reminders and post-visit rating requests as approved templates
- A template authoring screen — the clinic writes its own and submits to Meta from our dashboard
- Connection by Meta Embedded Signup or by pasting the IDs manually
- Ratings summary on the dashboard

> **Status:** the code is live; Meta's App Review granting advanced access is
> **still pending**, and no clinic account is connected. Until Meta approves and
> the app is published Live, WhatsApp carries no real traffic. This is an
> external dependency on Meta's queue, not remaining engineering.

### 5.4 The clinic-facing software

An installable React PWA, mobile-first, light and dark:

**Queue** (mark attended / no-show, step to future dates) · **Walk-in** ·
**Doctors** (roster, specialties, per-doctor calendars, token vs timed booking)
· **Schedules** (multi-session days, exact-date publishing, leave, and a preview
of what leave will cancel before you confirm) · **Patients** (deduplicated,
family members sharing one phone handled correctly) · **Treatments** ·
**Questions & messages** · **WhatsApp** · **Analytics** (call volume, booking
source, call-quality scoring) · **Billing** · **Support** (knowledge base, AI
support bot, ticketing with SLA escalation).

Roles: clinic owner, receptionist, doctor, platform support, super-admin.

---

## 6. How it is built

```
Patient's phone
      │  PSTN
      ▼
   Vobiz  ──── Indian DID + SIP trunk, per-clinic sub-account
      │
      ▼
  LiveKit  ──── India West, WebRTC/SIP media
      │
      ▼
  Voice agent (Fly.io, Mumbai)
      ├── STT   Soniox stt-rt-v5      (Japan region)
      ├── LLM   Gemini 2.5 Flash      (Vertex AI, asia-south1 / Mumbai)
      └── TTS   Soniox tts-rt-v1      (Japan region)
      │
      ▼
  FastAPI backend (Render)  ──►  Supabase Postgres (ap-south-1, Mumbai)
      │                     ──►  Redis / Upstash  (tokens, caches, telemetry)
      │                     ──►  Google Calendar API
      │                     ──►  Meta WhatsApp Cloud API
      │                     ──►  Razorpay
      ▼
  React PWA (Cloudflare Pages)
```

**Scale:** 26 database tables · 14 API router modules · 14 scheduled jobs ·
2,402 automated tests.

**Choices worth defending in technical diligence:**

- **The prompt cache is clinic-wide, not per-caller.** The stable clinic prompt, roster and tools are cached in Vertex; patient identity, current time and the caller's bookings stay in per-call private context. One cached object serves every caller of that clinic. Exactly one function composes a clinic prompt, enforced by a test that walks the syntax tree and fails if a second call site ever appears — because two call sites is precisely the bug that silently broke this in production (§13).
- **Token assignment never counts rows.** Atomic counter plus per-slot lock, with a concurrency test that races N callers at one slot.
- **The calendar write is part of the booking; the notification is not.** Calendar failure fails the booking cleanly. WhatsApp failure never does. A patient is never told they are booked when they are not, and never left unbooked because a message did not send.
- **A held token dies with its call.**
- **Tenant context comes from the number the patient dialled**, never from the number they call from.
- **Nothing reaches speech synthesis unsanitised.** Markdown, stray symbols and model-invented tags stripped at the boundary; clock times spoken as times; Telugu sent to TTS in Telugu script.

---

## 7. Technical benchmarks

Measured from production telemetry mirrored to Redis with 7-day retention.
These are the **server-side floor** — they exclude the carrier legs and handset
jitter the caller also hears, so a stopwatch in the caller's hand reads higher.

### Turn latency, real Telugu calls, 2026-08-09

| | Call A (16 turns) | Call B (21 turns) |
|---|---|---|
| p50 | 2,018 ms | **1,713 ms** |
| p95 | 2,888 ms | **2,222 ms** |
| max | 3,970 ms | **2,222 ms** |
| Prompt cache | miss on every turn | hit on all Telugu turns |

### Where the time goes

| Stage | Measured |
|---|---|
| Speech recognition finalise | 400–700 ms typical (2,400 ms worst observed, on a mid-sentence pause) |
| Language model, first token | 420–930 ms (cached prompt) |
| Speech synthesis, first audio | 480–700 ms |
| Barge-in stop | 600 ms (was 2,000 ms until fixed) |

### The honest reading

Conference feedback was that ~3 seconds makes the product unusable, and Call A
confirms that complaint was real. Call B, after the prompt-cache fix, removes
the long tail — nothing over 2.3 s.

It is still not where it needs to be. **A human receptionist answers in roughly
0.3 s.** This is a cascaded pipeline — speech → text → model → text → speech —
and every stage adds latency that tuning cannot remove. **The realistic floor
for this architecture is 800–1,000 ms.** Reaching the ~500 ms that feels
genuinely human requires a speech-to-speech model: a different architecture,
roughly double the variable cost, and unproven Telugu quality. That evaluation
is scoped and not yet run.

We publish these numbers rather than a marketing figure because latency is the
central technical risk and any serious investor will test it by calling.

### Correctness benchmarks

| Property | How it is held | Evidence |
|---|---|---|
| No double-booking | Atomic counter + per-slot lock | N-caller race test, exactly one winner |
| No cross-clinic data leak | Tenant ID on every query, cache key, calendar event, log line | Systematic cross-tenant sweep across every route, plus forged-token tests |
| No orphaned booking | Calendar write inside the transaction boundary | Booking-integrity suite |
| No lost reservation | Held token released on call end | Termination-path suite |
| Regression protection | A pinned test for every production bug ever found | 515 logged incidents, each with its test |

---

## 8. Competitive benchmark

### Against the category leader on data posture

Practo is the privacy bar most Indian doctors already know: ISO 27001, AWS,
published grievance process. If our documents stand next to theirs, the
data-safety objection is answered.

| Dimension | Practo-class platform | Vachanam | The pitch line |
|---|---|---|---|
| Data held | Full health profiles, consultations, orders, payments | Name + phone + one complaint line + token | We never build the honeypot |
| Organisational certification | ISO 27001 | **None yet** — our infrastructure vendors are SOC 2 / ISO certified | Lead with architecture, not badges. Never overclaim. |
| Call recordings | n/a to their core product | Never stored, by design | The strongest single line with doctors |
| Patient identity | Platform-wide accounts | Impossible by design — patients belong to one clinic | Their patients stay *their* patients |
| Retention | Policy statements | A daily software job, periods published | Enforced by code, not by PDF |
| DPDP role | Fiduciary for their consumer app | Processor; the clinic stays Fiduciary | The doctor keeps legal ownership |
| DPA offered to | Enterprise only | Every clinic | — |

*Practo entries are from their public materials and should be re-verified before
being quoted in writing.*

### Against the three competitor classes

| Class | Examples | What they do | Why we are not substitutable |
|---|---|---|---|
| **Patient marketplaces** | Practo, Bajaj Finserv Health, Lybrate | Aggregate demand, ask the patient to install an app, intermediate the clinic's relationship with its own patient | We are invisible to the patient and never own the relationship. Opposite business. |
| **Clinic management software** | Halemind, Docon, many regional players | Digitise records, billing, inventory | They do not answer the phone. Complementary — and our refusal to be an EMR is what keeps that true. |
| **Generic AI voice platforms** | Bland, Vapi, Retell | Sell a voice-agent toolkit | A clinic cannot buy a toolkit and be done. It needs Indian telephony, Indian-language speech that survives a noisy line, the token/queue model, split-shift doctor schedules, leave cascades, calendar, and DPDP posture. That assembly is the product; the voice model is a component. |

### Rules when pitching against them

1. Never claim ISO or SOC certification for Vachanam itself — say *"runs entirely on SOC 2 / ISO-certified infrastructure."*
2. Never disparage the incumbent. *"Different job, different data footprint"* wins the room.
3. Every claim must trace to a public document URL or a code-enforced behaviour. If a doctor's IT person asks, we show the mechanism.

---

## 9. Brand positioning

### Positioning statement

> For Indian clinic owners who lose patients to an unanswered phone, Vachanam
> is an AI receptionist that answers every call in the patient's own language
> and books the appointment correctly — unlike patient-facing apps, which
> require the patient to change how they seek care, and unlike clinic software,
> which manages records but never picks up the phone.

### The name

*Vachanam* (వచనం) means **word** — speech, an utterance, and in its older
sense, a promise given. The product is a promise that the phone gets answered.

### The tagline

**"Healing starts with being heard."**

It works on two levels at once, which is why it is the right line: the patient
is heard literally, by a system that listens instead of ringing out; and heard
in the older clinical sense, that care begins when someone attends to you. It
positions the product as an act of respect toward the patient rather than a
cost saving for the clinic — which is also how it should be sold, because
doctors do not enjoy being told their front desk is a cost centre.

### What we are, and are not

| We are | We are not |
|---|---|
| The front desk that never gets busy | A doctor, or any kind of medical advice |
| Invisible infrastructure behind the clinic's own number | A marketplace that owns the patient |
| A small, defensible data footprint | An EMR or a records system |
| Indian-language-first, Telugu-first | An English product with Indian languages bolted on |
| Priced against a receptionist's salary | An enterprise procurement cycle |

### Voice and tone

Calm, plain, unhurried — the tone of a good receptionist. In the product's own
speech this is a hard rule and not a style preference: the agent speaks the
loanwords a real receptionist uses rather than literary register, because a
patient who is spoken to in formal book-Telugu knows immediately they are
talking to a machine. In our written and sales material the same discipline
applies: concrete claims, no hype, numbers with their provenance attached. This
document is written in the brand's voice deliberately.

### Visual identity

A **monochrome clinic desk**. One neutral ground, near-black ink, and a single
sage-cream band as the only warm note. General Sans across every role,
self-hosted so the app works offline with no render-blocking font fetch. Dark
mode inverts the accent rather than dimming the palette. The visual language is
deliberately quiet — the software sits behind a doctor's practice, and nothing
about it should compete with the clinic's own identity.

---

## 10. Ideal customer and market

### The ideal first customer

- **Single-location clinic, 1–5 doctors**, dental / dermatology / diagnostics
- **20–80 inbound calls a day** — enough that calls get missed, few enough that there is no call-centre team
- **One receptionist**, paper or lightly digital
- **The owner is the decision-maker** and can say yes in one meeting
- **Telugu-speaking region** for the first cohort, because that is where our language quality is proven and where the founder is

We deliberately exclude hospitals and general medicine at this stage. They have
procurement committees, triage requirements we will not build, and liability
surface we will not accept.

### Market sizing — method, not a number

We are not going to put a fabricated TAM in this document. Here is the
arithmetic and where each input has to come from:

```
TAM  = (private outpatient clinics in India in our specialties)
       × (₹1,999 … ₹17,999 per month)

SAM  = clinics in Telugu- and Hindi-speaking regions
       with 1–5 doctors and ≥20 calls/day

SOM  = what one founder plus a small field team can reach
       in 18 months, at the close rate the first pilots reveal
```

- **Clinic counts** must come from a licensed registry or a purchased dataset, not from an estimate. We have not bought one.
- **Willingness to pay** is partly known: conference feedback said the original pricing was too high, which is why the ₹1,999 entry plan exists. That is a real signal, not a survey.
- **Close rate and payback** are unknown until pilots run.

An investor should read this section as: *we know exactly which three numbers
decide the size of this business, and we have not yet paid to learn them.*
That is a cheap, bounded piece of diligence and it is on the list.

---

## 11. Business model and unit economics

### Plans

Read directly from `backend/services/billing_math.py`, which is the single
source of truth the running application uses.

| Plan | Price / month | Included | Doctors | WhatsApp | Follow-up loop |
|---|---|---|---|---|---|
| **WhatsApp** | ₹1,499 | no phone line | 3 | ✅ | — |
| **Lite** | ₹1,999 | 1 number, 150 min (≈55 calls) | 3 | add-on | ✅ |
| **Starter** | ₹5,999 | 1 number, 700 min (≈250 calls) | 3 | add-on | ✅ |
| **Clinic** | ₹9,999 | 1 number, 1,500 min (≈540 calls) | 5 | ✅ | ✅ |
| **Multi** | ₹17,999 | 1 number, 3,000 min (≈1,080 calls) | unlimited | ✅ | ✅ |

Overage ₹5/min on every voice plan · WhatsApp add-on ₹1,499/mo for Lite and
Starter · extra number ₹1,999/mo · extra branch ₹7,999/mo, provisioned as a
full separate clinic. All plans include all 8 languages.

**We market in calls and meter in minutes.** A clinic owner reasons in calls;
our cost is minutes. The translation is done for them.

**GST:** prices are exclusive of 18% GST, but GST is currently **waived** in
code as a launch decision. One constant restores it.

**Trial:** every new clinic currently gets 14 days and 300 voice minutes.
(`CLAUDE.md` still says the trial was removed — the code is newer and the trial
is active. §19.)

### Unit economics

Variable cost ≈ **₹2.0/min typical, ₹2.6/min worst case** across telephony,
speech recognition, synthesis, the language model and media transport. Pricing
is built on a deliberately pessimistic **₹3/min**. Fixed cost per clinic is
**₹1,500/month** (₹1,200 phone number + ₹300 infrastructure share); a
WhatsApp-only clinic costs ₹300, having no number.

Gross margin **if a clinic burns its entire included bucket at the pessimistic
₹3/min** — the worst case reachable without overage revenue:

| Plan | Revenue | Worst-case cost | Margin |
|---|---|---|---|
| WhatsApp | ₹1,499 | ₹300 | **80%** |
| Lite | ₹1,999 | ₹1,950 | **2.5%** |
| Starter | ₹5,999 | ₹3,600 | **40.0%** |
| Clinic | ₹9,999 | ₹6,000 | **40.0%** |
| Multi | ₹17,999 | ₹10,500 | **41.7%** |

Every plan above Lite holds a ≥40% floor by construction, and a margin-guard
test fails the build if a pricing change breaks it.

**Lite is a deliberate exception.** At ₹1,999 the fixed ₹1,500 number cost is
too large a share for a 40% floor to be arithmetically possible. It exists to
reach clinics that would otherwise not buy at all, its downside is capped by
₹5/min overage, and it is carved out of the guard test explicitly rather than
quietly. Read Lite as customer acquisition, not profit.

**Realistic blended expectation:** at ~60% bucket utilisation and typical cost,
roughly **58% gross margin**, about **₹6,000 profit per clinic per month**.
Fixed overhead — servers, salaries — sits outside this and dominates at low
clinic counts.

**Current infrastructure burn before the first customer: ≈₹3,048/month.** This
business is cheap to keep alive and expensive to *distribute*.

---

## 12. Go-to-market

**The motion is field sales, and we should not pretend otherwise.** Indian
clinic owners do not buy software from a content funnel. They buy from someone
who sat in their waiting room and watched the phone ring out.

**The demo is the product.** The entire sales conversation can be a phone call:
hand the owner a number, let them call it in Telugu, let them try to confuse it.
Nothing in a deck competes with that, and it is why latency matters so much
commercially — the demo either feels like magic or feels like a robot, and the
difference is under a second.

**Onboarding is deliberately shallow.** A clinic goes live by forwarding its
number and entering its doctors and hours. No migration, no data import
required, no retraining. This is what makes a same-week close plausible and it
is a direct consequence of the "not an EMR" decision.

**The wedge is the entry plan.** ₹1,999 against a receptionist's monthly salary
is an easy first yes; the upgrade path to ₹5,999 and ₹9,999 is driven by minute
consumption, which we meter and show them.

**Expansion revenue is structural.** Extra numbers, the WhatsApp add-on, and
₹7,999 per additional branch mean a chain that starts with one location grows
account value without a new sale.

**Referral is the plausible second channel.** Doctors in a city know each other.
One clinic that visibly stops missing calls is a better sales asset than any
campaign. This is unproven and should not be modelled as a growth engine yet.

---

## 13. Engineering reality

Two things distinguish this codebase from a demo, and one is a warning.

**It is genuinely tested.** 2,402 automated tests, run on every push, gating
deployment. They cover what actually costs money or trust: concurrency, tenant
isolation, payment paths, and a fixed regression test for every production bug
ever found.

**Every production bug is written down.** `docs/FIXLOG.md` records 515 numbered
incidents — symptom, root cause, fix, and the test that pins it. That is
unusual discipline and it is why the system recovers from real-call failures
quickly.

**The warning — how subtle the failure modes are.** For an unknown period,
*every language-model turn in production ran with a cold prompt cache*. The
cache key is a hash of the instruction string, and the live call path and the
cache warmer were two separate pieces of code required to produce a
byte-identical string by developer discipline. They drifted twice. The symptoms
were reported as three unrelated complaints — the agent stated wrong dates, it
spoke stiff literary Telugu instead of how a receptionist talks, and it was
slow — and were nearly "fixed" three separate times by rewriting prompts. The
actual cause was one line of infrastructure. It is now one function with a test
that makes a second call site impossible.

The lesson generalises: in an AI voice product, quality regressions and latency
regressions are frequently the same bug wearing different clothes, and you
cannot find them without per-turn telemetry. We now have that telemetry.

---

## 14. Data protection and regulatory position

India's **Digital Personal Data Protection Act 2023** governs. Under it the
**clinic is the Data Fiduciary** and **Vachanam is the Data Processor**, bound
by a published Data Processing Agreement. HIPAA is a US statute and does not
apply to an Indian clinic serving Indian patients; we do not claim HIPAA
compliance, and no honest Indian vendor should.

**Data minimisation is architectural, not aspirational.** We store a first
name, a phone number, a one-line reason for the visit, and a token. We do not
store medical records, prescriptions, diagnoses, test results, scans or
government identifiers. **Vachanam is explicitly not an EMR** and the product
constraints forbid becoming one by accident.

- **Tenant isolation** is enforced on every query, cache key, calendar event and log line — the hardest constraint in the codebase. Breaching it is criminal liability under the DPDP Act, not a bug.
- **Call audio is not recorded in production.** Speech is transcribed in flight and the audio discarded. A narrow, environment-gated override exists for the founder's own number for testing and must be off before the first paying clinic.
- **Telemetry carries no PII** — last four digits of a phone, identifiers not names.
- **Calendar events** carry name, last-4 and token only. No medical detail reaches a doctor's calendar.
- **Retention is enforced by a daily job**, not by policy text.
- **Vachanam's own founder is locked out** of clinic patient screens by role checks. Platform administration does not include browsing patients.
- **Audit log** is append-only, with a PII denylist scanning even metadata values.
- Public: privacy policy, terms, DPA, refund policy, data-handling document, data-deletion page.

**Residency.** Database in Mumbai (`ap-south-1`). Voice agent in Mumbai.
Language model in Mumbai (`asia-south1`). Speech recognition and synthesis in
**Japan** — Soniox's nearest supported region. Disclosed rather than glossed,
because it is the one component that leaves India.

**Security posture:** JWT with instant revocation, rate limiting, security
headers, exact-origin CORS, secret scanning in CI, dependency scanning, an
adversarial audit against OWASP Top 10 and API Top 10 with every finding fixed
and regression-tested, and a ZAP scan in the pipeline.

---

## 15. Traction, stated plainly

**Paying clinics: zero. Pilot clinics: zero. Revenue: ₹0.**

What exists: a production system with live telephony, two configured test
clinics, real end-to-end Telugu calls that book, reschedule and cancel against
a real Google Calendar, and a founder who took clinic feedback at a conference
and repriced in response.

What has never happened: a real patient, of a real clinic, booking a real
appointment they then attended.

Everything in §2 about missed calls and lost revenue is untested until that
occurs. Weight this document accordingly: a technically mature product with
**zero commercial validation**. The material risk is not "can they build it" —
it is built — but "will clinics buy it, and does it survive contact with a real
front desk."

---

## 16. Metrics that will decide this business

The numbers to demand at the next update, in priority order:

| Metric | Why it decides things | Known today |
|---|---|---|
| **Missed calls recovered per clinic per week** | This is the entire value proposition, measured | Unknown |
| **p50 turn latency** | Below ~1.2 s the product feels human; above ~2 s owners call it a robot | 1,713 ms |
| **Booking completion rate** | Calls answered that end in a confirmed booking. The AI's actual competence. | Unmeasured on real patients |
| **Containment rate** | Calls handled with no human handoff | Unmeasured |
| **Minutes per clinic per month** | Drives both plan fit and gross margin | Unmeasured |
| **Trial → paid conversion** | Whether the demo survives two weeks of reality | No trials run |
| **Monthly churn** | Whether the follow-up loop actually retains | No customers |
| **CAC and payback** | Whether field sales works at this price point | No sales |
| **Uptime of the voice line** | A clinic's phone line is now our uptime | One machine today (§17) |

---

## 17. Risks

| Risk | Reality | What reduces it |
|---|---|---|
| **Latency** | p50 1.7 s against a human's ~0.3 s. Conference feedback already flagged it. | Cache and turn-taking fixes shipped. Sub-second needs a speech-to-speech architecture — scoped, not built, roughly doubles variable cost. |
| **No commercial proof** | Zero clinics. The revenue thesis is untested. | First pilot. Cheap to run; the product instruments its own hypothesis. |
| **Single point of failure** | The voice agent runs on **one machine** in Mumbai. If it dies, every clinic's phone line dies. | A second machine is a small change and an accepted debt at zero clinics. Must be fixed before the first paying customer. |
| **Meta dependency** | WhatsApp is built but gated on Meta's App Review, which we do not control. | Voice is the core product and needs no Meta approval. WhatsApp is upside. |
| **Vendor concentration** | Soniox for both speech recognition and synthesis; a single telephony provider. | The language-model layer already has automatic fallback. Speech has a documented alternate. Telephony does not — real concentration risk. |
| **Non-Telugu quality** | Seven other languages ship; only Telugu is validated at length. Hindi in particular has known issues. | Deliberate: Telugu-first, expand on demand. Do not oversell the other seven. |
| **Voice commoditisation** | Models get better and cheaper for everyone, including entrants. | The assembly and the clinic relationship are the moat, not the model. Speed matters more than cleverness. |
| **Regulatory** | DPDP enforcement is new and its rules are still settling. | Data minimisation means less exposure than any competitor holding records. |
| **Founder concentration** | One person: engineering, sales, support. | The honest mitigation is hiring, which is what capital is for. |

---

## 18. Where it goes, and what capital is for

The engineering is largely done. The unknowns are commercial. Capital converts
into four things:

1. **Pilot clinics** — a small number, run properly, instrumented, with the founder present. Validates or kills the §2 hypothesis within weeks.
2. **Latency** — evaluate speech-to-speech and re-price around its cost, or prove the cascaded floor is commercially good enough. This is the difference between "impressive demo" and "we forgot it wasn't a person."
3. **Reliability before revenue** — second agent machine, real on-call. Non-negotiable before a clinic's phone line depends on us.
4. **Distribution** — clinic sales in India is field sales, and it does not scale on content marketing.

### Immediately next (weeks)

First pilot clinics · Meta approval and WhatsApp live · second agent machine ·
speech-to-speech evaluation · **clinic data import** (designed, not built:
patient directory and appointment history as structured data, with any clinical
notes stored as a sealed, display-only archive no AI tool can read, so the "not
an EMR" boundary survives contact with a clinic's existing software) · UPI
autopay mandate so renewals stop depending on a manual payment.

### Next (months)

Sub-second conversation · Hindi and Tamil validated to the standard Telugu
already meets · multi-branch chains, where the ₹7,999 per-branch line becomes
meaningful revenue · deeper analytics — a clinic owner who can see *which*
calls were lost and what they were worth is a clinic owner who renews.

### Later, and honestly speculative

The same primitives — Indian-language voice, correct booking, a follow-up loop —
generalise beyond clinics. A real-estate sales-development variant is already
built and parked on a branch, unshipped. A doctor-facing secretary product was
scoped and parked pending demand. Both are optionality, not plan; neither
should be valued.

---

## 19. Corrections to older documents in this repository

Included because this file was asked to contain nothing false, and because
these documents are visible to anyone doing diligence.

| Document | Claim | Reality |
|---|---|---|
| `docs/pitch/data-safety-pitch.md` | Database in **Singapore** | Mumbai, `ap-south-1` |
| `docs/pitch/data-safety-pitch.md` | "700+ tests" | 2,402 |
| `docs/pitch/*`, and others | Links to `api.vachanam.in` | That DNS record does not exist. Legal pages are served from the Render host. |
| `docs/ROADMAP.md` | Phases 6–10 unstarted; WhatsApp deferred | All shipped; WhatsApp is built |
| `docs/MAIN_AGENDA.md` | Sarvam for speech; doctors manage the day by WhatsApp commands | Soniox for speech; no such WhatsApp command surface exists |
| `CLAUDE.md` | Free trial removed; signups start paused | Code re-enabled the 14-day trial for all signups on 2026-07-20 |
| `CLAUDE.md` | Launch offer pricing active | The offer table is empty; every plan bills at list price |
| `docs/STATUS.md` | Everything below the 2026-06-13 marker | Stale by design; only the top banners are current |

---

## 20. How to verify any claim here

| Claim type | Source of truth |
|---|---|
| Pricing, margins, plan gates | `backend/services/billing_math.py` |
| Data model | `backend/models/schema.py` |
| Voice agent capability | `agent/livekit_minimal/agent.py`, `agent/tools/booking_tools.py` |
| Latency | Redis key `lat:turns` — one line per caller turn, 7-day retention |
| Test count | `pytest tests --collect-only -q` |
| Production incidents | `docs/FIXLOG.md` |
| Legal commitments | `docs/legal/`, and the live pages the backend serves |
| Brand tokens and type | `frontend/src/index.css` |
| Hard product constraints | `CLAUDE.md`, "Hard constraints" |

---

*Vachanam — healing starts with being heard.*
