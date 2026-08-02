# WhatsApp hub + cross-channel design

**Date:** 2026-08-02 · **Decided by:** Vinay (brainstorming session)
**Companion doc:** `2026-08-02-whatsapp-tech-provider-design.md` covers the Meta
ownership/credential model. This one covers the product: the page, the tabs, and
how voice and WhatsApp become one product instead of two.

**Revised the same day** after researching how WhatsApp automation actually
works alongside a clinic's own phone. The inbox is gone; see §0.

**Goal:** a WhatsApp surface a clinic opens to *set up and watch* its
automation — connect the number, control its templates, send announcements, see
what the AI did — while the receptionist keeps answering patients on the clinic
phone exactly as they do today.

---

## 0. The finding that reshaped this design

A WhatsApp number can run in one of two shapes:

- **API-only** — the number lives on the Cloud API and the WhatsApp Business app
  stops working for it. Nobody can answer from a phone. If we don't build an
  inbox, no human can ever reply.
- **Coexistence** — the number runs on the Business app **and** the Cloud API at
  once ("Onboard Business app users" in Meta's console). The receptionist keeps
  using WhatsApp on the clinic phone; Meta keeps history in sync; and **every
  message they send from the phone fires an `smb_message_echoes` webhook to us,
  body included** (also on edit and delete).

Coexistence costs: throughput capped at 20 messages/sec (irrelevant at clinic
scale); disappearing messages, view-once, live location and broadcast lists are
disabled on that number; groups, voice/video calls, catalogue and channels are
not available through the API. Contacts sync, and up to 180 days of chat history
can sync with the clinic's approval.

Two consequences:

1. **We don't need an inbox.** The receptionist's phone is the inbox, and it is a
   better app than anything we would build. Our value is the automation, the
   templates, the broadcasts and the reporting.
2. **Human-reply detection is free.** `smb_message_echoes` tells us a person
   answered, so the AI can step aside automatically — no takeover button, no
   unread state, no realtime UI.

And the correction to the privacy worry: **message bodies reach our servers
either way** — the inbound webhook carries the patient's text (the AI cannot
answer without it) and the echo carries the receptionist's. The choice is not
whether we see them; it is how long we keep them and where. That is a knob, and
we set it to "barely" (D14).

Sources: [Onboard WhatsApp Business app users](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/) ·
[smb_message_echoes reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/smb_message_echoes)

---

## Decisions (binding)

| # | Decision | Rationale |
|---|---|---|
| D1 | One nav item **WhatsApp**, three tabs: Activity · Templates · Broadcasts, plus Setup | Separate page as asked; sidebar grows by one |
| D2 | Nav is **capability-driven** | A WhatsApp-only clinic sees no Queue/Walk-in/Doctor-leave; a voice-only clinic sees no WhatsApp. Same code, smaller app (Vinay) |
| D3 | Owner **and** receptionist get the page | Vinay's call. Broadcasts carry a confirm-with-count-and-cost gate |
| D4 | Templates tab = **list + live preview** | Custom templates are what Meta rejects; seeing their own words rendered with real patient/doctor/token stops `{{1}}` from being scary |
| D5 | Templates are **English only** | Vinay: WhatsApp is English at this clinic. Existing `wa_templates.template_lang()` collapses to a constant `en`; no `language` column until multi-language returns |
| D6 | Free-text AI replies **mirror the patient's language** | Telugu in → Telugu out, Tenglish in → Tenglish out. Costs nothing (same Gemini path as calls) |
| D7 | **AI answers instantly; a human reply silences it for 24h on that thread** | Detected from `smb_message_echoes`, no button, no clock config. The patient never waits, and the receptionist overrides by simply typing |
| D8 | Broadcast audience v1 = **all contacts the clinic holds** | Vinay will discuss segmentation with clinics first. Filter seam left in place |
| D9 | Timeline is a **query-time union**, not a materialized table | No new write paths; a few hundred rows per patient |
| D10 | **Bridge mode then Tech Provider**, one code path | Build now on our own WABA, switch per clinic when App Review clears (§6) |
| D11 | Cross-channel continuity carries **context, never a token hold** | RULE 3 is not negotiable — a held token dies with its call |
| D12 | **Coexistence-first.** The clinic keeps its phone; API-only is not supported in v1 | The receptionist already lives in WhatsApp on the desk phone (§0) |
| D13 | **No inbox, no thread UI, no takeover button** | Superseded by D12 — we would be competing with WhatsApp itself and losing |
| D14 | **Patient message bodies are never persisted.** We store metadata + the text OUR AI sent | Smallest DPDP surface that still answers "what did the bot tell my patient?" |
| D15 | Patient text lives only in **Redis with a TTL** while the AI is composing a reply | Same lifetime as the conversation it serves |
| D16 | A config flag can turn full capture on later, default **off** | Mirrors `transcript_capture_enabled` for calls. A seam, not a feature |

---

## 1. Information architecture

```
Sidebar (owner)          Sidebar (WhatsApp-only clinic)
  Dashboard                 Dashboard
  Queue                     Patients
  Walk-in                   WhatsApp
  Treatments                Settings
  Patients                  Support
  WhatsApp   ← new
  Doctors
  Settings
  Support
```

Nav renders from org capabilities (`voice_enabled`, `whatsapp_enabled`), derived
from plan + connection state. Not a new permission system — a filter over the
existing role-keyed `NAV` map in `frontend/src/components/Shell.jsx`.

The cross-channel story lives on the **Patient** page, not here — that is where
staff already go for a person's history (§5.2).

## 2. Tab: Activity

**Job:** show the owner what the automation did, without becoming a chat client.

Reverse-chronological list, one row per exchange:

```
Ramesh · …7554   AI answered "clinic timings"           11:04
Lakshmi · …3321  AI booked token 12, Dr Srinivas        10:52
Suresh · …9087   you replied from the clinic phone      10:31
Anita · …4410    reminder template delivered            09:00
```

Each row carries: patient (name if on record, else masked number), what
happened, who did it (`AI` / `clinic phone` / `system`), delivery state, time.
Clicking a row opens the **patient**, not a chat thread.

What is deliberately absent: the patient's words, a reply box, unread counts,
realtime. To read or answer a conversation, the receptionist opens WhatsApp on
the clinic phone — which is where it already is.

## 3. Tab: Templates

**Job:** decide what the clinic says, in its own words, without getting rejected.

- Left: every template for this branch — the four built-in ones
  (`booking_confirm`, `appt_reminder`, `rating_ask`, `leave_rebook`) plus custom
  ones. Each row carries its Meta status chip: `approved` / `in review` /
  `rejected` / `draft`.
- Right: live preview — the message rendered as a WhatsApp bubble with real
  sample data (this clinic's name, a real doctor, a plausible date/token), the
  editable body, the placeholder map, usage count, and the status.
- Rejected templates show Meta's reason inline, with edit-and-resubmit.
- Toggle per template controls whether the platform sends it. A disabled or
  unapproved template is skipped by the send path with a log line — never a
  crash, never a stuck job (RULE 4/8).
- Custom template creation: name, category (utility/marketing), body with
  placeholder insertion, preview, submit. Status arrives asynchronously via the
  `message_template_status_update` webhook.

## 4. Tab: Broadcasts · and Setup

**Broadcasts** — pick an approved template → audience = all contacts the clinic
holds → **confirm screen showing recipient count, opt-out exclusions and
estimated cost** → throttled send with live progress, then a history of past
sends with delivered/failed counts.

*"All contacts the clinic holds"* means exactly: patients of **this branch**
with a non-null phone, not opted out, not erased. No other clinic's patients can
ever appear (RULE 1).

Guardrails: opt-out enforced before every send, per-day cap, throttle, marketing
category labelled as billable.

**Setup** — connect/disconnect, number and display name, coexistence state,
quality rating, messaging tier, delivery health (last inbound, failures in 24h),
and a banner when Meta downgrades quality or a token is revoked.

## 5. Cross-channel

### 5.1 Shared memory
Patient identity is the phone number in both channels already. The chat AI reads
recent call outcomes for that number; the voice agent reads recent chat activity
(what happened, not the patient's words — D14). Both branch-scoped (RULE 1).

### 5.2 One timeline
On the Patient page: calls and WhatsApp activity interleaved by time. Calls
render as outcome cards (booked / cancelled / no answer, transcript when
retained); WhatsApp renders as activity rows plus the AI's own outbound text.
Built as a query-time union of the call tables and `wa_events` (D9).

### 5.3 Fallbacks (exactly three)
| Trigger | Action | Note |
|---|---|---|
| Inbound call missed (after hours, busy, agent down) | WhatsApp template: "Sorry we missed your call — reply here and I'll book you" | The missed-call revenue the product exists for |
| Reminder call unanswered | Send the reminder as a template instead | Cheaper than a wasted call |
| Doctor follow-up undelivered after 3 attempts | "The doctor has a message for you — reply to hear it" | RULE 9: **no health detail in the body** |

Deliberately **not** built: WhatsApp-goes-quiet → outbound call.

### 5.4 Continuity without breaking RULE 3
A booking that moves between channels carries context (patient, doctor,
preferred slot) but **never a live token hold**. WhatsApp re-runs availability
and takes its own short-TTL hold.

### 5.5 Who is speaking (D7)
```
patient message  → AI replies in seconds
receptionist types on the phone → smb_message_echoes → AI silent on that
                                  thread for 24h, logged as answered_by=human
24h of no human message → AI resumes automatically
```
No button, no per-clinic hours, no settings. A human typing is the override.

## 6. Bridge mode → Tech Provider (D10)

Three independent Meta gates, not one chain:

1. **Test WABA, dev mode** — available now: send, templates, webhooks; 5
   recipients. No verification, no App Review.
2. **App Live toggle** — basic settings only (privacy policy URL, already served
   at `/privacy`; icon; category). Not App Review. Unlocks real webhooks.
3. **Business verification + App Review advanced access** — needed *only* to
   touch other businesses' WABAs, i.e. Embedded Signup / coexistence onboarding
   for real clinics.

**Bridge mode:** the pilot number lives on Vachanam's own WABA. An unverified
business gets 250 business-initiated conversations/24h and free service replies
inside the 24h window — ample for a pilot. First pilot number: **Vinay's second
number, with the WhatsApp Business app installed on it**, so the pilot exercises
coexistence exactly as a clinic will.

**One code path, one flag per branch:**

```
branch.wa_token_enc IS NULL  → platform token + Vachanam WABA   (bridge mode)
branch.wa_token_enc present  → the clinic's token + their WABA  (tech provider)
```

Everything above the token resolver never knows which mode it is in. Migrating a
clinic later is: click Connect once, coexistence onboarding writes the token,
next message goes out on their own WABA. No rewrite, no data migration, no
downtime; clinics may sit in different modes simultaneously. This is why the
per-branch token resolver must exist from day one even though day one is
entirely bridge mode.

## 7. Data model (additive)

| Object | Fields | Notes |
|---|---|---|
| `wa_events` **new** | branch_id, patient_id?, patient_phone, direction, kind (`patient_message`, `ai_reply`, `human_reply`, `template`, `broadcast`), ai_body?, template_name?, wa_message_id, status, error?, created_at | **No patient body column** (D14). `ai_body` holds only what our AI sent |
| `wa_templates` **new** | branch_id, name, category, body, placeholders JSONB, meta_status, rejection_reason?, enabled, usage_count, synced_at | Per-branch because templates live per WABA |
| `wa_broadcasts` **new** | branch_id, template_id, recipient_count, sent/failed counts, status, created_by, created_at | Audit + history |
| `patients.wa_opted_out_at` **new column** | timestamptz | STOP handling, checked before every non-service send |
| `branches.wa_*` | per companion doc: `wa_waba_id`, `wa_token_enc`, `wa_status`, … | `wa_phone_number_id` already exists |
| Redis `wa:ctx:{branch}:{phone}` | rolling conversation window for the AI | TTL ≤ 24h (D15). Never copied to Postgres |

Retention: `ai_body` is our own text and follows the ordinary retention
schedule; patient erasure wipes the rows. There is no patient message body to
prune because there is none stored.

## 8. Constraints this design must satisfy

- **RULE 1** — every query branch-scoped; a broadcast can never reach another
  clinic's patients; one branch's token can never send on another's number.
- **RULE 3** — no token hold survives its conversation (§5.4).
- **RULE 4** — a WhatsApp failure never fails or blocks a booking.
- **RULE 5** — inbound branch = the receiving `phone_number_id`, never the sender.
- **RULE 9** — no health detail in any template body or notification; logs carry
  phone last-4 and ids only.
- Plan gate `WHATSAPP_PLANS = {clinic, multi}` stays the single source.

## 9. Build order and gates

**This supersedes the build order in the companion Tech Provider doc**, where
Embedded Signup was slice 1. It moves to slice 6: nothing else depends on it, and
App Review is easier to pass once the real product exists to record.

| # | Slice | Gate |
|---|---|---|
| 1 | Per-branch token resolver + `wa_events` / `wa_templates` schema + echo webhook handling (`smb_message_echoes` → `answered_by=human`, AI silenced 24h) | none |
| 2 | Templates tab (preview, custom, approval webhooks) | test WABA |
| 3 | Activity tab + capability-driven nav | test WABA |
| 4 | Timeline on the Patient page + the three fallbacks | pilot number on our WABA |
| 5 | Record App Review videos **using the real product** | slices 2–3 done |
| 6 | Coexistence / Embedded Signup connect flow | Tech Provider approved |
| 7 | Broadcasts | — (last, so it can slip) |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Broadcast to every contact tanks the number's quality rating | Opt-out enforced, per-day cap, throttle, confirm screen with count + cost, quality banner in Setup |
| Custom template rejected by Meta | Live preview before submit, reason shown inline, one-click resubmit |
| "The bot said something wrong" and we can't see the patient's side | We keep the AI's own words + the activity trail; full capture exists as a default-off flag (D16) the clinic can consent to |
| Coexistence disables features the clinic used (view-once, broadcast lists, groups) | Named in onboarding copy before they connect |
| A clinic wants API-only (no phone) | Not supported in v1; the inbox that would serve it is deferred, not designed away |
| Reply attempted outside the 24h window | Only templates are offered outside it; free text is never attempted |
| Bridge-mode 250/day ceiling hit during pilot | Verification already in flight; ceiling lifts on approval |

## 11. Deferred (explicitly not v1)

Inbox / thread UI / human takeover button (D13) · API-only numbers · broadcast
segmentation · per-language templates · WhatsApp→call fallback · materialized
interactions table · scheduled broadcasts · receptionist/owner permission split.

## 12. Definition of done

A clinic connects its existing WhatsApp number without giving up the phone the
receptionist already uses. Patients get instant AI answers; the moment the
receptionist types, the AI goes quiet on that thread. The owner opens
**WhatsApp** to see what the automation did, turn templates on and off, write one
of their own and watch it get approved — and on a patient's page sees this
morning's call and this evening's chat as one story, without Vachanam holding a
single word the patient typed.
