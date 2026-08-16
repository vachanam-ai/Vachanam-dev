# Vachanam pricing model — 2026-08-16

## Decision

Vachanam has two public products:

| Item | Price | What it covers |
|---|---:|---|
| Vachanam Voice platform | ₹1,999/branch/month | one DID, cloud allocation, dashboard, unlimited doctors, scheduling and support workflows |
| Voice usage | ₹6/minute | STT, LLM, TTS, media transport and carrier usage |
| WhatsApp software add-on | ₹1,499/Voice branch/month | bot, booking actions, templates, reminders and dashboard integration |
| WhatsApp-only | ₹1,999/branch/month | the WhatsApp software without a DID or voice usage; up to 3 doctors |
| Additional branch or phone number | ₹1,499/month | separate DID and isolated branch setup |
| Meta message fees | direct at cost to clinic | paid by the clinic to Meta from the clinic-owned WABA |

The first 100 clinics receive 14 calendar days completely free. During this
trial there is no platform fee, voice-minute cap, card requirement, or automatic
charge. The trial ends at an absolute timestamp and the service pauses unless
the clinic explicitly activates paid service. The former 500-minute first-cycle
credit is retired for new clinics; it is not stacked on top of this offer.

The fixed platform fee may renew by autopay. Variable voice usage is never
auto-debited or auto-recharged at launch: the completed cycle is priced by the
server, shown to the owner, and paid manually from Plan & billing.

The proposed “free WhatsApp after 1,000 minutes” waiver is deliberately not a
launch rule. A fixed recurring mandate cannot safely vary month to month
without credits, refunds or subscription replacement, and that complexity is
not worth introducing before WhatsApp onboarding is live. Keep the published
₹1,499 add-on predictable; reconsider a volume reward after real cohort data.

## Why this structure

The old ₹4,999-for-500-minutes presentation looked like approximately ₹10 per
minute even though much of that price recovered the phone number and fixed
cloud cost. Separating those components makes the marginal rate visibly ₹6.
It also stops a quiet clinic subsidising a high-volume clinic and prevents an
unexpected overage cliff.

Hybrid platform-plus-usage pricing is familiar in voice AI: Bland publishes
both zero-base usage and paid platform tiers with lower usage rates
([Bland pricing](https://app.bland.com/pricing)). A ₹1,999 platform fee also
sits within the range Indian clinics already see for clinic software; for
example, Cufront publishes ₹1,250–₹1,500/month annual-billing tiers
([Cufront pricing](https://www.cufront.com/)).

## Unit economics

The conservative cost model in `backend/services/billing_math.py` is:

- AI/media: ₹2.25/minute
- carrier usage: ₹0.65/minute
- total variable cost: ₹2.90/minute
- DID plus fixed infrastructure allocation: ₹1,499/branch/month

At ₹6/minute, the usage line has ₹3.10 gross profit per minute, 106.9% markup
on cost and 51.7% gross margin on voice revenue. The table includes Razorpay's
standard domestic 2% fee plus 18% GST on that fee (2.36% effective). It remains
a contribution-margin model: salaries, sales, support, refunds and bad debt are
not included.

| Monthly voice use | Customer bill | Modelled service cost | Gateway fee | Contribution | Margin |
|---:|---:|---:|---:|---:|---:|
| 0 min | ₹1,999 | ₹1,499 | ₹47 | ₹453 | 22.7% |
| 500 min | ₹4,999 | ₹2,949 | ₹118 | ₹1,932 | 38.6% |
| 1,000 min | ₹7,999 | ₹4,399 | ₹189 | ₹3,411 | 42.6% |
| 2,000 min | ₹13,999 | ₹7,299 | ₹330 | ₹6,370 | 45.5% |

WhatsApp-only contributes about ₹1,653/month, or 82.7%, after the ₹299 fixed
allocation and standard domestic gateway fee. The ₹1,499 Voice add-on
contributes about ₹1,165/month, or 77.7%, under the conservative assumption
that it receives another full ₹299 allocation; if the existing branch already
absorbs that infrastructure, its incremental contribution is 97.6% before
support labour.

The Founding 100 trial is an explicit acquisition budget. “Unlimited” means
there is no billable minute ceiling, so the cash exposure depends on real use:

| Average trial usage | Cost per trial clinic | Cost for 100 clinics |
|---:|---:|---:|
| 100 minutes | ₹1,789 | ₹178,900 |
| 500 minutes | ₹2,949 | ₹294,900 |
| 1,000 minutes | ₹4,399 | ₹439,900 |
| 2,000 minutes | ₹7,299 | ₹729,900 |

The theoretical one-line ceiling is much larger: 14 continuously occupied
24-hour days equal 20,160 minutes, or about ₹59,963 including the fixed clinic
allocation. If all 100 trial lines were continuously occupied, exposure would
be about ₹59.96 lakh. That is not a forecast, but it is the honest cash-risk
boundary of a truly uncapped offer. Keep the existing single-line concurrency,
fraud controls, and real-time cost alerts active; do not silently introduce a
marketing minute cap.

This is deliberately not described as a 100% margin offer; it is acquisition
spend. Paid usage has 106.9% markup on variable cost, equivalent to 51.7% gross
margin before fixed costs. Trial access remains protected by one-clinic
eligibility, serialized first-100 allocation, normal fraud/rate controls, and
the hard 14-day expiry. Clinics may be invited to provide honest feedback after
the trial, but a positive testimonial is optional and is never a condition of
free service.

## WhatsApp ownership and billing

Use the clinic-owned WABA model:

1. Vachanam, as Tech Provider, onboards the clinic through Embedded Signup and
   receives permission to manage the WABA, templates and messaging actions.
2. The clinic adds and owns its Meta payment method.
3. Meta charges the clinic directly for message usage.
4. Vachanam charges ₹1,499/month when WhatsApp is added to Voice, or
   ₹1,999/month for WhatsApp-only.

Meta distinguishes Tech Providers from Solution Partners and says only
Solution Partners can extend a line of credit and manage billing through
credit sharing
([WhatsApp partner roles](https://whatsappbusiness.com/partners/become-a-partner/)).
Under credit sharing, the business pays the provider and the provider receives
Meta's aggregate invoice
([Meta Embedded Signup collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/du6gzjv/embedded-signup)).

Vachanam should not take that credit risk at launch. Direct clinic billing
avoids message-price changes, reconciliation, collections and one clinic's
unpaid Meta usage becoming Vachanam's liability. A consolidated reseller bill
can be reconsidered later through a Solution Partner when volume justifies it.

## Billing rules

- Display platform and usage as separate lines everywhere.
- Bill voice from the first billable minute; no bundled monthly allowance.
- Give the first 100 eligible clinics an unlimited 14-day trial; do not add a
  separate minute credit to their first paid cycle.
- Stamp the exact allowance onto each billing-cycle ledger row and use that
  value for access control, dashboard usage and renewal billing.
- Preserve paid legacy subscriptions for renewal, but offer only Vachanam
  Voice and WhatsApp-only to new signups and plan changes.
- Never mark Meta message charges up or collect them while clinics are on
  direct Meta billing.
