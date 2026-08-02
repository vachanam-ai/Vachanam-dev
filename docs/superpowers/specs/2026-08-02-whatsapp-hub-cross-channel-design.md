# WhatsApp hub + cross-channel design

**Date:** 2026-08-02 · **Decided by:** Vinay (brainstorming session)
**Companion doc:** `2026-08-02-whatsapp-tech-provider-design.md` covers the Meta
ownership/credential model. This one covers the product: the page, the tabs, and
how voice and WhatsApp become one product instead of two.

**Goal:** a WhatsApp surface a clinic opens daily — connect the number, control
its templates, answer patients, send announcements — and a patient story that
reads as one conversation whether it happened on the phone or in chat.

---

## Decisions (binding)

| # | Decision | Rationale |
|---|---|---|
| D1 | One nav item **WhatsApp**, four tabs: Inbox · Templates · Broadcasts · Setup | Separate page as asked; sidebar grows by one, not three |
| D2 | Nav is **capability-driven** | A WhatsApp-only clinic sees no Queue/Walk-in/Doctor-leave; a voice-only clinic sees no WhatsApp. Same code, smaller app (Vinay) |
| D3 | Owner **and** receptionist get all four tabs | Vinay's call. Compensated by a confirm-with-count gate on broadcasts |
| D4 | Templates tab = **list + live preview** | Custom templates are the risky part; seeing their own words rendered with real patient/doctor/token stops `{{1}}` from being scary and cuts Meta rejections |
| D5 | Templates are **English only** | Vinay: WhatsApp is English at this clinic. No per-language template variants in v1. Existing `wa_templates.template_lang()` collapses to a constant `en`; no `language` column until multi-language returns |
| D6 | Free-text AI replies **mirror the patient's language** | Telugu in → Telugu out, Tenglish in → Tenglish out. Costs nothing (same Gemini path as calls) and avoids answering a Telugu-speaking patient with an English wall |
| D7 | Staff reply **pauses the AI for that patient** until *Hand back to AI*; auto-resume after 24h of staff silence | Two voices answering one patient reads badly; the auto-resume stops a forgotten thread going dead |
| D8 | Broadcast audience v1 = **all contacts the clinic holds** | Vinay will discuss segmentation with clinics first. Filter seam left in place |
| D9 | Timeline is a **query-time union**, not a materialized table | No new write paths; a few hundred rows per patient. Materialize only if it gets slow |
| D10 | **Bridge mode then Tech Provider**, one code path | Build against our own WABA now, switch per clinic when App Review clears. See §6 |
| D11 | Cross-channel continuity carries **context, never a token hold** | RULE 3 is not negotiable — a held token dies with its call |

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

The **cross-channel story does not live here.** It lives on the Patient page,
because that is where staff already go for a person's history and the only place
a call and a chat belong to the same object (§5.2).

## 2. Tab: Inbox

**Job:** answer patients; see what the AI already said.

- Thread list: patient name (or number), last message, relative time, unread
  count, and an owner chip — `AI handling` or `You're handling`.
- Thread view: full conversation, inbound/outbound, delivery ticks, template
  messages visually distinct from free text.
- Reply box. Typing and sending sets the thread to human-owned (D7): the AI
  stops replying to that patient, a banner explains it, and a **Hand back to AI**
  button restores autonomy. 24h of staff silence auto-hands back.
- The 24-hour window is surfaced, not hidden: when it has closed, the reply box
  is replaced by "This patient hasn't messaged in 24h — you can only send an
  approved template", with the template picker inline.

**Sending is never possible when:** the branch is not connected, the plan does
not include WhatsApp, the patient has opted out, or (for templates) the template
is not approved.

## 3. Tab: Templates

**Job:** decide what the clinic says, in its own words, without getting rejected.

- Left: every template for this branch — the four built-in ones
  (`booking_confirm`, `appt_reminder`, `rating_ask`, `leave_rebook`) plus custom
  ones. Each row carries its Meta status chip: `approved` / `in review` /
  `rejected` / `draft`.
- Right: live preview — the message rendered as a WhatsApp bubble with real
  sample data (this clinic's name, a real doctor, a plausible date/token), the
  editable body, the placeholder map, usage count, and the status.
- Rejected templates show Meta's rejection reason inline, with an Edit and
  resubmit action.
- Toggle per template controls whether the platform sends it at all. A disabled
  or unapproved template is skipped by the send path with a log line — never a
  crash, never a stuck job (RULE 4/8).
- Creating a custom template: name, category (utility/marketing), body with
  placeholder insertion, preview, submit to Meta. Status arrives asynchronously
  via the `message_template_status_update` webhook.

## 4. Tab: Broadcasts and Tab: Setup

**Broadcasts** — pick an approved template → audience = all contacts the clinic
holds → **confirm screen showing recipient count, opt-out exclusions, and
estimated cost** → throttled send with live progress.

*"All contacts the clinic holds"* means exactly: patients of **this branch**
with a non-null phone, not opted out, not erased. No other clinic's patients can
ever appear (RULE 1). History of past sends with
delivered/failed counts. Guardrails: opt-out enforced, per-day cap, throttle,
marketing category clearly labelled as billable.

**Setup** — connect/disconnect, number and display name, quality rating,
messaging tier, delivery health (last inbound received, failures in 24h), and a
banner when Meta downgrades quality or a token is revoked.

## 5. Cross-channel

### 5.1 Shared memory
Patient identity is the phone number in both channels already. The chat AI reads
recent call outcomes for that number; the voice agent reads recent chat. Nobody
is asked their name twice. Both remain branch-scoped (RULE 1).

### 5.2 One timeline
On the Patient page: calls and messages interleaved by time. Calls render as
outcome cards (booked / cancelled / no answer, plus transcript when retained);
messages render as bubbles. Built as a query-time union of the call tables and
`wa_messages` (D9).

### 5.3 Fallbacks (exactly three)
| Trigger | Action | Note |
|---|---|---|
| Inbound call missed (after hours, busy, agent down) | WhatsApp template: "Sorry we missed your call — reply here and I'll book you" | The missed-call revenue the product exists for |
| Reminder call unanswered | Send the reminder as a template instead | Cheaper than a wasted call, protects against no-shows |
| Doctor follow-up undelivered after 3 attempts | "The doctor has a message for you — reply to hear it" | RULE 9: **no health detail in the template body** |

Deliberately **not** built: WhatsApp-goes-quiet → outbound call. Costs voice
minutes and reads as pushy.

### 5.4 Continuity without breaking RULE 3
A booking that moves between channels carries context (patient, doctor,
preferred slot) but **never a live token hold**. WhatsApp re-runs availability
and takes its own short-TTL hold. A hold never outlives the conversation that
created it.

## 6. Bridge mode → Tech Provider (D10)

Three independent Meta gates, not one chain:

1. **Test WABA, dev mode** — available now: send, templates, webhooks; 5
   recipients. No verification, no App Review.
2. **App Live toggle** — basic settings only (privacy policy URL — already
   served at `/privacy` — icon, category). Not App Review. Unlocks real webhooks.
3. **Business verification + App Review advanced access** — needed *only* to
   touch other businesses' WABAs, i.e. Embedded Signup for real clinics.

**Bridge mode:** the pilot number lives on Vachanam's own WABA. An unverified
business gets 250 business-initiated conversations/24h (visible in WhatsApp
Manager) and free service replies inside the 24h window — ample for a pilot.
First pilot number: **Vinay's own second number** (no clinic commitment needed,
no existing WhatsApp history to migrate).

**One code path, one flag per branch:**

```
branch.wa_token_enc IS NULL  → platform token + Vachanam WABA   (bridge mode)
branch.wa_token_enc present  → the clinic's token + their WABA  (tech provider)
```

Everything above the token resolver — templates, inbox, broadcasts, fallbacks,
timeline — never knows which mode it is in. Migrating a clinic later is: click
Connect once, Embedded Signup writes the token, next message goes out on their
own WABA. No rewrite, no data migration, no downtime, and clinics may sit in
different modes simultaneously.

This is why the per-branch token resolver must exist from day one even though
day one runs entirely in bridge mode.

## 7. Data model (additive)

| Object | Fields | Notes |
|---|---|---|
| `wa_messages` **new** | branch_id, patient_id?, patient_phone, direction, body, template_name?, wa_message_id, status (sent/delivered/read/failed), error?, created_at | Powers inbox + timeline. Bodies are patient content → same retention treatment as call transcripts; wiped by patient erasure |
| `wa_templates` **new** | branch_id, name, category, body, placeholders JSONB, meta_status, rejection_reason?, enabled, usage_count, synced_at | Per-branch because templates live per WABA |
| `wa_broadcasts` **new** | branch_id, template_id, recipient_count, sent/failed counts, status, created_by, created_at | Audit + history |
| `patients.wa_opted_out_at` **new column** | timestamptz | STOP handling, checked before every non-service send |
| `branches.wa_*` | per companion doc: `wa_waba_id`, `wa_token_enc`, `wa_status`, … | `wa_phone_number_id` already exists |

## 8. Constraints this design must satisfy

- **RULE 1** — every query branch-scoped; a broadcast can never reach another
  clinic's patients; one branch's token can never send on another's number.
- **RULE 3** — no token hold survives its conversation (§5.4).
- **RULE 4** — a WhatsApp failure never fails or blocks a booking.
- **RULE 5** — inbound branch = the receiving `phone_number_id`, never the sender.
- **RULE 9** — no health detail in any template body or notification; logs carry
  phone last-4 and ids only; message bodies pruned on the retention schedule.
- Plan gate `WHATSAPP_PLANS = {clinic, multi}` stays the single source.

## 9. Build order and gates

**This supersedes the build order in the companion Tech Provider doc**, where
Embedded Signup was slice 1. It moves to slice 6: nothing else depends on it, and
App Review is easier to pass once the real product exists to record.

| # | Slice | Gate |
|---|---|---|
| 1 | Per-branch token resolver + `wa_templates` + `wa_messages` schema | none |
| 2 | Templates tab (preview, custom, approval webhooks) | test WABA |
| 3 | Inbox + human takeover | test WABA → Live toggle for real messages |
| 4 | Timeline + the three fallbacks | pilot number on our WABA |
| 5 | Record App Review videos **using the real product** | slices 2–3 done |
| 6 | Embedded Signup connect flow | Tech Provider approved |
| 7 | Broadcasts | — (last, so it can slip) |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Broadcast to every contact tanks the number's quality rating | Opt-out enforced, per-day cap, throttle, confirm screen with count + cost, quality banner in Setup |
| Custom template rejected by Meta | Live preview before submit, rejection reason shown inline, resubmit in one click |
| Staff forgets a thread they took over | 24h auto-hand-back to the AI |
| Reply attempted outside the 24h window | Reply box swaps to a template picker; free text is not offered |
| Message bodies become a DPDP liability | Same retention + erasure path as call transcripts |
| Bridge-mode 250/day ceiling hit during pilot | Verification is already in flight; the ceiling lifts on approval |

## 11. Deferred (explicitly not v1)

Broadcast segmentation (pending clinic conversations) · per-language templates ·
WhatsApp→call fallback · materialized interactions table · scheduled broadcasts ·
receptionist/owner permission split.

## 12. Definition of done

A clinic opens **WhatsApp**, sees its number connected and healthy, turns on the
templates it wants, writes one of its own and watches it get approved, answers a
patient the AI was already handling and hands the thread back — and on that
patient's page sees this morning's phone call and this evening's chat as one
story.
