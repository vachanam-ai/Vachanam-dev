# WhatsApp pricing and plan design

**Date:** 2026-08-02 · **Decided by:** Vinay
**Depends on:** `2026-08-02-whatsapp-tech-provider-design.md` (clinic-owned WABA,
model A) and `2026-08-02-whatsapp-hub-cross-channel-design.md` (MVP batching —
this spec **amends** its MVP1/MVP4 split, see §8).

**Goal:** decide what Vachanam charges for WhatsApp, given that under the
clinic-owned-WABA model Meta bills the clinic directly and we never see that
invoice.

---

## 1. The three prices

| Offer | Internal key | Price | Ships |
|---|---|---|---|
| **WhatsApp-only plan** — no DID, no voice, 3 doctors | `wa` | **₹1,499/mo** | MVP1 |
| **Bundled** — included in Clinic and Multi | (existing) | ₹0 | MVP1 |
| **WhatsApp add-on** for Lite and Starter | addon flag | **₹1,499/mo** | MVP2 |

**One number everywhere.** WhatsApp costs ₹1,499 whether bought standalone or
bolted onto a voice plan. A clinic never sees the same feature priced two ways,
which removes the "why do they pay less than me" conversation before it starts,
and it keeps `billing_math` to a single figure.

All prices exclusive of 18% GST, currently waived platform-wide (`GST_WAIVED`).

### The ladder

```
WhatsApp only   ₹1,499   no DID, no voice, 3 doctors   ← cheapest door in
Lite            ₹1,999   150 min
Lite + WA       ₹3,498
Starter         ₹5,999   700 min, 3 doctors
Starter + WA    ₹7,498                                 ← ₹2,501 below Clinic
Clinic          ₹9,999   1,500 min, 5 doctors, WA included
Multi          ₹17,999   3,000 min, unlimited, WA included
```

Starter + add-on stays meaningfully under Clinic, so a clinic that also needs
minutes or a 4th doctor still upgrades. The add-on exists to capture clinics who
want only WhatsApp and would otherwise buy nothing.

## 2. What the fee buys, and what it does not

**Our fee is software only:** the AI chat agent, booking, integrations, the
dashboard, templates, and support.

**The clinic pays Meta directly.** They own the WABA and attach their own
payment method (model A). We never see the invoice, cannot meter it, and do not
mark it up. This is a structural consequence of model A, not a policy choice —
absorbing message costs would require the Vachanam-owned WABA of model B, which
was rejected for the ~25-number ceiling, pooled quality ratings, and carrying
every clinic's Meta bill and GST.

**It removes a monetization lever.** Because we cannot meter their messages,
WhatsApp pricing must be a flat fee. There is no per-message markup available,
unlike voice minutes.

### What the clinic actually pays Meta

Meta India rates effective 2026-01-01: **utility ₹0.115/message**, marketing
₹0.8631/message, authentication ₹0.115/message. All four Vachanam templates
(`booking_confirm`, `appt_reminder`, `rating_ask`, `leave_rebook`) are
**utility**. Patient-initiated service conversations have been free and
unlimited since 2024-11-01, and utility templates delivered inside an open
24-hour customer service window are currently free.

| Clinic type | Monthly Meta bill |
|---|---|
| **WhatsApp-only** — patient messages first, so the service window is open and the confirmation lands inside it; only next-day reminders fall outside | **~₹25–30** at ~200 bookings |
| **Voice plan + WhatsApp** — booking happens on the phone, so no window is open and the confirmation is a paid utility message | **~₹150** at ~540 bookings |

Both are rounding errors against ₹1,499. **Sell it as a differentiator:** most
Indian BSPs add a 20–50% per-message markup; Vachanam adds none.

**Unverified risk:** several resellers claim Meta begins charging for utility
templates inside the 24-hour window on 2026-10-01. Meta's own pricing
documentation does not confirm this. If true it roughly triples a
WhatsApp-only clinic's bill — from ~₹30 to ~₹150/mo — which is still trivial,
and still the clinic's cost, not ours. No pricing action needed; re-check the
rate card in September.

## 3. Changes to `backend/services/billing_math.py`

```python
PLANS["wa"] = Plan(1_499, 0, 0.0, 3, "WhatsApp")   # 0 minutes, 0 overage

WHATSAPP_ADDON_RUPEES = 1_499
WHATSAPP_ADDON_PLANS  = frozenset({"lite", "solo"})           # may BUY it
WHATSAPP_PLANS        = frozenset({"clinic", "multi", "wa"})  # INCLUDED

def whatsapp_enabled(plan: str, addon: bool) -> bool:
    """Single gate for every WhatsApp capability check."""
    return plan in WHATSAPP_PLANS or (addon and plan in WHATSAPP_ADDON_PLANS)
```

Every current `plan in WHATSAPP_PLANS` call site moves to `whatsapp_enabled(...)`.
Entitlement is one boolean on the organization — not a new table.

`wa` carries `included_minutes=0` and `overage_per_min=0.0` because it buys no
voice at all. Voice must be **hard-blocked** for it, not merely unmetered
(§5.2).

## 4. Margin invariant — the DID assumption must be split

`test_every_plan_holds_40pct_margin_at_worst_case` computes:

```python
WORST_COST_PER_MIN, INFRA = 3.0, 1500.0
cost = p.included_minutes * WORST_COST_PER_MIN + INFRA
```

The flat ₹1,500 **includes the per-clinic DID**. Applied to `wa` that gives
`0 × 3 + 1500 = ₹1,500` against a ₹1,499 price — a negative margin for what is
in fact the most profitable plan we sell. A second bug: the overage assertion
divides by `overage_per_min`, which is 0 for `wa` → `ZeroDivisionError`.

Fix — make the fixed cost per-plan:

```python
DID_RUPEES = 1_200    # per-clinic phone number; voice plans only
BASE_INFRA =   300    # hosting/support share; every plan
# voice plans: DID_RUPEES + BASE_INFRA = 1,500   (unchanged, all four still pass)
# wa plan:     BASE_INFRA only          =   300
```

`wa` then holds **~80% worst-case margin** — the best in the table, because it
buys no DID and burns no per-minute cost. The overage assertion skips any plan
with `overage_per_min == 0`.

## 5. Plan plumbing for `wa`

### 5.1 Schema

`Organization.plan` is a Postgres enum `("lite","solo","clinic","multi")`
(`backend/models/schema.py`). Adding `wa` needs a migration
(`ALTER TYPE plan_type ADD VALUE 'wa'`), following the `gg30` precedent that
added `lite`.

`config.py` gains `razorpay_plan_wa_id` (Lite has no Razorpay plan id either —
out of scope here, but worth noting the same gap exists).

### 5.2 Voice is blocked, not merely absent

- `call_blocked` must refuse for plan `wa` — a WhatsApp-only clinic has no DID
  and no minutes, so an inbound or outbound call is a configuration error, not
  an overage.
- `_dispatch_reminder_call` in `backend/jobs/pre_appt_reminder.py` must skip
  plans without voice. The job's existing gate is
  `settings.voice_plane_configured`, which describes **our platform**, not the
  clinic's plan — so it currently would run for a `wa` branch and attempt a
  call for a clinic that bought no line.
- `_send_wa_reminder` in the same job is already correctly gated by
  `wa_enabled` and needs no change.

### 5.3 Manual bookings must confirm

`send_booking_confirmation` is called from exactly one place —
`agent/tools/booking_tools.py`, the voice path. `queue.create_walkin` does not
send it. For a WhatsApp-only clinic a receptionist-entered booking is a normal
path, so it must send `booking_confirm` too. RULE 4 still holds: a WhatsApp
send failure must never fail the booking.

## 6. Judgment calls

- **No launch-offer discount on WhatsApp.** `OFFER_PRICES` exists to lower the
  *voice* barrier; ₹1,499 is already the cheapest thing we sell.
- **3 doctors on `wa`**, mirroring Lite and Starter. Zero variable cost, but the
  ladder stays legible.
- **No fair-use message cap.** Gemini classification is ~₹0.02/message; metering
  is infrastructure for a problem we do not have. Revisit if a clinic runs hot.
- **`GST_WAIVED` applies identically** to `wa` and to the add-on.

## 7. Product scope required to justify the price

A ₹1,499 standalone plan is only honest if WhatsApp handles the whole job.
**"Please call us" is banned as a WhatsApp reply** (Vinay, 2026-08-02).

| Patient message | Bot behaviour |
|---|---|
| New booking request | **Books in chat** — matches doctor, offers real slots, assigns an atomic token, writes the calendar event, confirms |
| Reschedule / cancel | Existing `wa_actions` flow |
| Anything in the clinic's FAQ | Answers strictly from the FAQ |
| A real clinic question we cannot answer | *"Let me check with the doctor and get back to you."* → writes a `ClinicQuestion` → **surfaces in the dashboard** (shipped 2026-08-02) → doctor answers → patient gets the reply |
| Off-topic or prompt-injection ("write me some code") | Graceful deflection back to clinic business. Never "call us", never complies |

**Doctor notification is the dashboard, not WhatsApp.** Vinay accepted either.
The dashboard path already exists end to end. Messaging a doctor from a
Vachanam number requires our own WABA, doctor opt-in, and an approved template
(business-initiated, outside any service window) — a later addition.

### 7.1 No token holds in chat

RULE 3 ("a held token dies with its call") has no analogue in chat: there is no
call to end, and a patient may reply four hours later.

**Decision: assign the token only at the moment the patient confirms**, via the
same atomic Redis INCR. RULE 2 is untouched and no expiry machinery is built.
If the slot filled while the patient was deciding, the bot says so and offers
the next one.

Rejected: a TTL-based hold. It reserves capacity for someone who may never
reply, which in a 150-token day is real lost revenue, and it adds an expiry
subsystem for no gain.

### 7.2 Conversation state IS stored

Reversing the 2026-08-02 coexistence decision (Vinay: *"you can store whatsapp
chats also no problem, we can update policies"*). Multi-turn booking needs
memory, and the `WhatsAppSession` table with its `session_data` JSONB column
already exists and is currently dead code.

**Hard sequencing constraint:** `/privacy` and `/data-deletion` currently state
*"We do not store the contents of your WhatsApp messages"* and *"There is no
WhatsApp inbox in Vachanam"*, deployed 2026-08-02 and about to be handed to
Meta app review as our data-deletion URL. **The policy update must ship in the
same release as the storage code**, never after. Serving a live policy that
denies storage we perform is a DPDP exposure.

`test_data_deletion_promises_only_built_behaviour` asserts those sentences
verbatim and will fail the moment storage lands — the guardrail is already in
place and must be honoured, not deleted.

**Storage scope, stated concretely so it is not read two ways:**
`WhatsAppSession.session_data` holds the **last 10 message turns** (sender,
text, timestamp) plus the in-progress booking draft. Keyed `(branch_id, patient
phone)` — RULE 1. Deleted by `patient_erasure` alongside the patient record, and
pruned by the daily retention job after **30 days idle**. No message is stored
outside this window, and there is still no staff-facing inbox screen — the
conversation is the bot's working memory, not an archive for humans to browse.

## 8. Amendment to the MVP batching

The hub spec put chat booking in MVP4. Vinay moved it into MVP1 (2026-08-02):
MVP1 must be a **complete, sellable WhatsApp-only product**, and the add-on for
voice plans becomes MVP2.

**MVP1 gains:** the `wa` plan and its migration, voice blocking, the chat
booking brain, manual-booking confirmations, out-of-scope deflection, the
margin-invariant fix, and the policy update from §7.2.

**Scope warning (raised, overruled, recorded):** this makes MVP1 the largest
slice of the WhatsApp work rather than a week-sized one. Vinay's call —
a standalone product sellable to a new clinic beats a feature attached to plans
already sold.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Storage ships before the policy update | §7.2 sequencing; the existing test fails red until the docs match |
| Add-on cannibalises the Clinic upgrade | Starter + add-on = ₹7,498 vs Clinic ₹9,999, which also adds 800 minutes and 2 doctors |
| `wa` clinic somehow triggers a voice call | §5.2 blocks at `call_blocked` and at reminder dispatch; both need tests |
| Meta raises utility rates 2026-10-01 | Clinic's cost, not ours; ~₹30 → ~₹150/mo. Re-check the rate card in September |
| Chat booking double-books | RULE 2 atomic INCR unchanged; §7.1 removes the hold path entirely |
| A `wa` clinic expects voice | Plan name and signup copy must say "WhatsApp only — no phone line" |

## 10. Definition of done

A clinic with no phone line from us signs up on the `wa` plan at ₹1,499,
connects its own WhatsApp number, and its patients book, reschedule, cancel and
get answers entirely in WhatsApp — with confirmations and reminders arriving
automatically, unanswered questions reaching the doctor in the dashboard, and
the clinic's own Meta bill under ₹50 that month.

---

## Sources

- [Pricing on the WhatsApp Business Platform — Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)
- [WhatsApp Business API Pricing in India (2026) — AiSensy](https://aisensy.com/pricing)
- [WhatsApp Business API Pricing in 2026: Conversation Categories, Costs, and What Changed — Blueticks](https://blueticks.co/blog/whatsapp-business-api-pricing-2026)
- [WhatsApp API Pricing India (Jul 2026): ₹ Rate Card — Whautomate](https://whautomate.com/whatsapp-business-api-pricing-india)
