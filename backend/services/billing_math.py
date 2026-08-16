"""Pure billing/unit-economics math for the super-admin console.

Single source of truth for plan pricing (CLAUDE.md — FINAL, change only on
Vinay's instruction) and Vachanam's own cost model. Pure functions: no DB,
no I/O — unit-tested in tests/unit/test_billing_math.py.

All amounts in WHOLE RUPEES (floats only where overage rates demand it).
"""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Plan:
    base_rupees: int
    included_minutes: int
    overage_per_min: float  # rupees
    max_doctors: int | None  # None = unlimited
    display_name: str
    included_branches: int = 1
    has_voice: bool = True


# Public pricing, 2026-08-16: one transparent branch platform fee plus metered
# voice. Internal keys remain stable for database/webhook compatibility; old
# tier rows are supported but cannot be sold to new clinics.
PLANS: dict[str, Plan] = {
    "wa": Plan(1_999, 0, 0.0, 3, "WhatsApp", has_voice=False),
    "lite": Plan(1_999, 150, 6.0, 3, "Lite (legacy)"),
    "solo": Plan(1_999, 0, 6.0, None, "Vachanam Voice"),
    "clinic": Plan(4_999, 0, 6.0, 10, "Growth (legacy)"),
    "multi": Plan(6_999, 0, 6.0, None, "Scale (legacy)", included_branches=2),
}

# New clinics can choose only these plans. Lite remains runtime-compatible for
# old rows but is retired from signup and self-serve plan changes.
SELLABLE_PLANS = frozenset({"solo", "wa"})

ADDITIONAL_BRANCH_RUPEES = 1_499
ADDITIONAL_NUMBER_RUPEES = 1_499

# Fixed monthly cost per clinic, split by whether the plan buys a phone number.
# Until 2026-08-02 this was one flat Rs1,500 constant with the DID folded in —
# which charged a WhatsApp-only clinic for a line it never gets (0*3 + 1500 vs
# a Rs1,499 price = a NEGATIVE margin on our most profitable plan).
DID_RUPEES = 1_200.0  # per-clinic DID; voice plans only
BASE_INFRA = 299.0    # hosting/support allocation per branch


def fixed_cost_for(plan: str) -> float:
    """Vachanam's own fixed monthly cost to serve one clinic on this plan."""
    p = PLANS.get(plan)
    has_voice = bool(p and p.has_voice)
    # Scale includes two branches, and each branch needs its own DID plus its
    # share of infrastructure. Counting only one made the pricing guard report
    # an imaginary extra Rs1,500 of monthly margin on that plan.
    return (
        (DID_RUPEES + BASE_INFRA) * p.included_branches
        if has_voice and p is not None
        else BASE_INFRA
    )

# Dormant offer machinery is retained for backward compatibility. The empty
# OFFER_PRICES mapping means every clinic pays list price from its first cycle.
OFFER_MONTHS = 3
# Restored 2026-07-21: after the 14-day trial, the first three paid months use
# an acquisition price. Starter/Clinic/Multi retain 10–15% margin at the
# conservative full-bucket cost model. Lite is the known exception because its
# fixed DID cost makes a 10% worst-case margin impossible below its list price.
# EMPTIED 2026-08-04 (Vinay: "remove discount pricings"). Every plan now bills
# at its list price from the first paid month.
#
# The mechanism is kept rather than deleted: `effective_price` falls through to
# the standard price when a plan has no entry here, so re-running an
# acquisition offer later is one dict away — and, more importantly, nothing
# else in billing has to change to turn it off. The same lever was used on
# 2026-07-20 and the offer restored on 07-21.
OFFER_PRICES: dict[str, int] = {}


def in_offer_window(subscription_started_at, now=None) -> bool:
    """True while the org is inside its first 3 PAID months. No subscription
    yet (trial / pre-signup pricing display) → True: the offer is what they
    are being sold. Window = 92 days from first payment (~3 calendar months,
    predictable regardless of month lengths)."""
    from datetime import datetime, timedelta, timezone

    if subscription_started_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    started = subscription_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return now < started + timedelta(days=31 * OFFER_MONTHS - 1)


def effective_price(plan: str, subscription_started_at=None, now=None) -> tuple[int, bool]:
    """(rupees, is_offer) — the price this org actually pays this cycle."""
    p = PLANS.get(plan)
    if p is None:
        return 0, False
    if plan in OFFER_PRICES and in_offer_window(subscription_started_at, now):
        return OFFER_PRICES[plan], True
    return p.base_rupees, False


# Voice-agent languages available per plan (agent.i18n codes). None = every
# language the platform supports. 2026-07-12 (Vinay): ALL plans get all
# languages — language is zero-variable-cost; plans now differentiate on
# minutes, doctors and the follow-up loop instead.
PLAN_LANGUAGES: dict[str, list[str] | None] = {
    "lite": None,
    "solo": None,
    "clinic": None,
    "multi": None,
}

# Voice CLONING: feature REMOVED entirely 2026-07-24 (Vinay — Soniox is the TTS
# and its clone quality wasn't good enough; catalog voices only). The old
# CLONING_PLANS / cloning_allowed / PREMIUM_VOICE_PLANS gates died with it.

# Treatment FOLLOW-UP voice loop — 2026-07-15 (Vinay: "follow-up is the main
# part to retain patients, include it"). Available on EVERY plan: it is just
# metered outbound minutes (revenue, not a cost sink), so gating retention
# behind premium made no economic sense.
FOLLOWUP_PLANS = ("lite", "solo", "clinic", "multi", "wa")

# Plans that INCLUDE WhatsApp (confirmations, reminders, rating asks, chat).
# 2026-08-02: "wa" joins clinic/multi — WhatsApp IS that plan. The old note
# "message cost ~Rs0.40/booking, absorbed" is obsolete: under the clinic-owned
# WABA model (spec 2026-08-02-whatsapp-tech-provider) the CLINIC pays Meta
# directly, so our marginal message cost is zero and unmeterable.
WHATSAPP_PLANS = frozenset({"wa"})

# Voice plans may buy WhatsApp for Rs1,499/month per branch. The clinic owns its
# WABA and pays Meta's message charges directly; this is Vachanam's bot,
# automation and support fee, not a resale of Meta messages.
WHATSAPP_ADDON_RUPEES = 1_499
WHATSAPP_ADDON_PLANS = frozenset({"lite", "solo", "clinic", "multi"})


def whatsapp_enabled(plan: str, addon: bool = False) -> bool:
    """Single gate for every WhatsApp capability check."""
    return plan in WHATSAPP_PLANS or (bool(addon) and plan in WHATSAPP_ADDON_PLANS)

# Zero is an unlimited-trial sentinel. Usage is measured for the cost ledger,
# but it is not billed or exhausted during the 14-day founding trial.
TRIAL_MINUTES = 0
TRIAL_UNLIMITED = True

# Founding 100 capacity. The legacy credit constant remains at zero for client
# compatibility; the acquisition offer is now the free service window.
FOUNDING_CLINIC_SLOTS = 100
FOUNDING_CREDIT_MINUTES = 0

# The absolute timestamp, not minutes, ends the offer. Service pauses with no
# automatic payment if the clinic has not explicitly activated a paid plan.
PILOT_DAYS = 14

# CLAUDE.md: all prices are exclusive of 18% GST. An overage invoice (a real
# charge) adds GST on top; B2B clinics reclaim it via input credit.
GST_RATE = 0.18
# 2026-07-17 (Vinay): "for now remove gst 18%" — launch pricing is charged
# as-is with NO GST line added on top. Flip to False to restore GST-on-top
# everywhere (breakdowns keep the gst field, it just computes 0 while waived).
GST_WAIVED = True


def _gst_on(amount: float) -> float:
    return 0.0 if GST_WAIVED else round(amount * GST_RATE, 2)

# Vachanam's own VARIABLE cost floor (CLAUDE.md, 2026-06 repricing): per voice
# minute (Vobiz + speech services + Gemini + LiveKit) + DID rent.
# NOTE: this is VARIABLE only — it excludes fixed overhead (servers, salaries,
# misc), which is amortised across total minutes and dominates at low volume.
AI_MEDIA_COST_PER_MIN = 2.25
VOBIZ_USAGE_COST_PER_MIN = 0.65
VARIABLE_COST_PER_MIN = AI_MEDIA_COST_PER_MIN + VOBIZ_USAGE_COST_PER_MIN
DID_COST_PER_MONTH = DID_RUPEES


def month_revenue(plan: str, status: str, minutes_used: float) -> float:
    """Revenue Vachanam earns from this org this month.

    Only ACTIVE orgs pay. Trial = free (cost absorbed); paused/cancelled = no
    billing. Current plans have no bundled minutes, so every voice minute is
    billed at the plan's per-minute rate. Legacy plans keep their old bucket.
    """
    if status != "active":
        return 0.0
    p = PLANS.get(plan)
    if p is None:
        return 0.0
    overage = max(0.0, minutes_used - p.included_minutes)
    return round(p.base_rupees + overage * p.overage_per_min, 2)


def month_expense(minutes_used: float, did_count: int) -> float:
    """What this org costs Vachanam this month: voice minutes + DID rent.
    DIDs cost while held regardless of usage or org status."""
    return round(minutes_used * VARIABLE_COST_PER_MIN + did_count * DID_COST_PER_MONTH, 2)


def included_minutes(plan: str) -> int:
    p = PLANS.get(plan)
    return p.included_minutes if p else 0


def included_minutes_for(plan: str, status: str, adjustment: int = 0) -> int:
    """Voice-minute allowance for an org THIS month, honoring the trial grant
    and the super-admin per-clinic ``adjustment`` (signed delta, floored at 0).

    An unlimited trial has no finite bucket and is represented by zero. Any
    other status gets the plan's own included bucket.
    Single source for both the clinic dashboard donut and the super-admin view.
    """
    if status == "trial" and TRIAL_UNLIMITED:
        return 0
    base = TRIAL_MINUTES if status == "trial" else included_minutes(plan)
    return max(0, base + (adjustment or 0))


def allowance_adjustment(
    plan: str,
    *,
    cycle_included: int | None = None,
    org_adjustment: int = 0,
    founding_credit: int = 0,
) -> int:
    """Adjustment to pass to allowance math.

    A paid cycle is the entitlement ledger. Organization-level founding credit
    is only a staging value before the first cycle exists and can be cleared by
    an early renewal, so runtime gates must prefer the stamped cycle allowance.
    """
    if cycle_included is not None:
        return int(cycle_included) - included_minutes(plan)
    return int(org_adjustment or 0) + int(founding_credit or 0)


def overage_breakdown(
    plan: str, minutes_used: float, status: str = "active", adjustment: int = 0
) -> dict:
    """Itemised overage bill for one cycle — the single source for what a clinic
    is charged for minutes beyond its included bucket, and the exact amount sent
    to Razorpay (in paise).

    Razorpay does not know about minutes; it charges a rupee total. The
    "per-minute" billing is THIS math: overage_minutes × overage_rate, + 18% GST.

    Example (solo plan, 1000 minutes used): included 100 → 900 overage × ₹5 =
    ₹4500 + ₹810 GST = ₹5310 total = 531000 paise.
    """
    included = included_minutes_for(plan, status, adjustment)
    p = PLANS.get(plan)
    rate = p.overage_per_min if p else 0.0
    used = int(round(minutes_used))
    overage_min = (
        0 if status == "trial" and TRIAL_UNLIMITED
        else max(0, used - included)
    )
    overage_amount = round(overage_min * rate, 2)
    gst = _gst_on(overage_amount)
    total = round(overage_amount + gst, 2)
    return {
        "plan": plan,
        "included_minutes": included,
        "minutes_used": used,
        "overage_minutes": overage_min,
        "overage_rate": rate,
        "overage_amount": overage_amount,
        "gst": gst,
        "total_with_gst": total,
        "amount_paise": int(round(total * 100)),
    }


def subscription_order_breakdown(
    plan: str,
    cycle_minutes_used: float = 0.0,
    adjustment: int = 0,
    subscription_started_at=None,
    whatsapp_addon: bool = False,
) -> dict:
    """What a Razorpay activation/renewal order charges (#341, Vinay 2026-07-12:
    GST ON TOP, overage collected WITH the renewal).

    total = plan base + previous-cycle overage minutes × rate, + GST on the
    whole subtotal (0 while GST_WAIVED). First activation passes
    cycle_minutes_used=0 (the unlimited trial is free service and is never
    billed). #391: base honors the first-3-months launch-offer price —
    pass the org's subscription_started_at; None (first activation) = offer.
    """
    p = PLANS.get(plan)
    if p is None:
        return {"plan": plan, "base": 0, "overage_minutes": 0, "overage_amount": 0.0,
                "gst": 0.0, "total": 0.0, "amount_paise": 0, "is_offer": False}
    base, is_offer = effective_price(plan, subscription_started_at)
    included = max(0, p.included_minutes + (adjustment or 0))
    over_min = max(0, int(round(cycle_minutes_used)) - included)
    overage_amount = round(over_min * p.overage_per_min, 2)
    # WhatsApp rides on the PLAN invoice from the renewal after purchase — one
    # bill, not a second subscription to manage (Vinay 2026-08-03: "from next
    # month on entire billing should come together (number+whatsapp)"). Charged
    # only where it is an add-on: on clinic/multi/wa it is already in the price,
    # so billing it again would double-charge.
    addon_amount = (
        float(WHATSAPP_ADDON_RUPEES)
        if whatsapp_addon and plan in WHATSAPP_ADDON_PLANS
        else 0.0
    )
    subtotal = round(base + overage_amount + addon_amount, 2)
    gst = _gst_on(subtotal)
    total = round(subtotal + gst, 2)
    return {
        "plan": plan,
        "base": base,
        "is_offer": is_offer,
        "overage_minutes": over_min,
        "overage_amount": overage_amount,
        "whatsapp_addon": addon_amount,
        "gst": gst,
        "total": total,
        "amount_paise": int(round(total * 100)),
    }


def whatsapp_addon_order_breakdown() -> dict:
    """The one-off charge that switches WhatsApp on mid-cycle.

    Full ₹99 for the remainder of the current cycle, not pro-rated. Pro-rating
    this line adds cycle-boundary and refund edge cases to
    a money path for a few rupees. From the next renewal the amount is folded
    into subscription_order_breakdown instead, so this is charged exactly once.
    """
    base = float(WHATSAPP_ADDON_RUPEES)
    gst = _gst_on(base)
    total = round(base + gst, 2)
    return {
        "base": WHATSAPP_ADDON_RUPEES,
        "gst": gst,
        "total": total,
        "amount_paise": int(round(total * 100)),
    }


def next_cycle_start(today: date) -> date:
    """First day of the month AFTER ``today`` — when a clinic-scheduled plan
    change takes effect (never mid-month, so a switch can't shrink the bucket
    the clinic already paid for)."""
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def add_month(anchor: date, months: int = 1) -> date:
    """``anchor`` shifted by whole months, keeping the SAME day-of-month.

    Vinay 2026-08-01: a clinic's included minutes must run from the day they
    paid to that same day next month — not to a fixed 30 days (which drifts a
    little every cycle: Jan 31 + 30d lands on Mar 2) and not to the 1st.

    Days that do not exist in the target month clamp to that month's last day,
    so a 31st anchor bills on Feb 28/29 and then returns to the 31st — the
    anchor is never mutated, so the clamp cannot walk the date backwards month
    after month.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last_day))


def cycle_window(anchor: date, today: date) -> tuple[date, date]:
    """The billing window containing ``today`` for a subscription that started
    on ``anchor``: ``[start, end)``, start inclusive, end exclusive.

    Metering must count minutes over THIS window. Counting over the calendar
    month reset every clinic's bucket on the 1st regardless of when they paid
    (Vinay 2026-08-01), so a clinic that paid on the 20th silently got a fresh
    bucket 11 days later.
    """
    if today < anchor:
        # Pre-start (clock skew, or a future-dated anchor): the cycle that
        # would END at the anchor.
        return add_month(anchor, -1), anchor
    months = (today.year - anchor.year) * 12 + (today.month - anchor.month)
    start = add_month(anchor, months)
    if start > today:  # day-of-month not reached yet this month
        months -= 1
        start = add_month(anchor, months)
    return start, add_month(anchor, months + 1)


def minutes_exhausted(
    plan: str, minutes_used: float, status: str = "active", adjustment: int = 0
) -> bool:
    """True when the org has used up its INCLUDED bucket for the month
    (hard-block trigger).

    B3: the bucket is the SAME one the dashboard shows — `included_minutes_for`,
    including the super-admin `minutes_adjustment` (#169). Trials have no
    minute bucket; their exact end time is enforced separately in
    `call_blocked`.
    """
    inc = included_minutes_for(plan, status, adjustment)
    return inc > 0 and minutes_used >= inc


def call_blocked(
    status: str,
    plan: str,
    hard_block_on_exhaust: bool,
    minutes_used: float,
    trial_ends_at=None,
    adjustment: int = 0,
) -> str | None:
    """Why an incoming call for this org must NOT be served, or None.

    Returns 'paused' | 'cancelled' | 'trial_expired' | 'minutes_exhausted'
    | None. The voice agent must still ANSWER and speak one polite line
    (RULE 8 — never dead air), then hang up.

    trial_expired is defense-in-depth: the daily trial_pause job flips status
    to 'paused', but if that job hasn't run yet an expired trial must not keep
    getting free AI service (currently about Rs2.90/min variable cost).
    """
    if status in ("paused", "cancelled"):
        return status
    if status == "trial" and trial_ends_at is not None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ends = trial_ends_at
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if ends < now:
            return "trial_expired"
    # Paying plans may opt into a minute-bucket hard stop. Trials deliberately
    # bypass minute exhaustion: the offer is unlimited until `trial_ends_at`.
    if status != "trial" and hard_block_on_exhaust and minutes_exhausted(
        plan, minutes_used, status, adjustment
    ):
        return "minutes_exhausted"
    # 2026-08-02 (WA MVP1 Task 7): a plan with zero included minutes (`wa`)
    # bought no DID and no voice at all — an inbound call reaching this org is
    # a CONFIGURATION error, not a billing state. Checked LAST, after every
    # existing status/exhaustion branch, so it can never shadow a more specific,
    # more actionable reason: paused/cancelled/trial_expired/minutes_exhausted
    # all tell the org WHY billing blocked them, and none of those checks
    # inspect the plan's minute bucket, so moving this earlier would risk a
    # `wa` org that is ALSO paused/cancelled being told the wrong reason. This
    # only fires once none of those apply — e.g. an active `wa` org somehow
    # dialed at all (should never happen; the DID was never provisioned).
    p = PLANS.get(plan)
    if p is not None and not p.has_voice:
        return "no_voice_plan"
    return None


# ── autopay mandate ceiling (Vinay 2026-08-07) ───────────────────────────────
# A UPI e-mandate fixes ONE number up front: the most we may ever debit. Vinay:
# "keep it as low as possible and still covered to any extent. calculate it
# cleverly by taking max calls cases into consideration."
#
# Low and covered pull against each other, so the ceiling is derived, not
# guessed:
#
#   ceiling = (base + whatsapp_addon + worst_overage) x GST headroom
#
# WORST_OVERAGE is where the "max calls" thinking goes. The theoretical maximum
# is meaningless — one DID carries one call at a time, so a month is ~43,200
# minutes and a ceiling covering that would be lakhs, which is exactly what
# makes a clinic refuse to sign. Two bounds make it realistic instead:
#
#   1. Volume bound: a clinic running 3x its plan (its bucket plus two more)
#      is already an upgrade conversation, not a normal month.
#   2. Money bound: overage is capped at OVERAGE_CEILING_MINUTES. Rs15,000 of
#      overage in one month is an extreme month for any single-DID clinic, and
#      beyond it the mandate is the wrong instrument anyway — the debit falls
#      back to a payment link (that fallback has to exist regardless, because
#      no finite ceiling can cover every case).
#
# GST_HEADROOM is applied even while GST_WAIVED is True. If GST is ever
# switched back on, every debit rises 18% overnight; a ceiling set without it
# would reject every debit and force every clinic to re-authorise a mandate.
# Headroom is free — an unused ceiling costs nobody anything.

OVERAGE_MULTIPLE = 2          # bucket + 2 more = 3x plan volume
OVERAGE_CEILING_MINUTES = 3_000
MANDATE_GST_HEADROOM = 1.18   # applied even while GST_WAIVED (see above)


def mandate_worst_overage_minutes(plan: str) -> int:
    """Overage minutes a mandate ceiling should still cover for this plan."""
    p = PLANS.get(plan)
    if not p or not p.has_voice:
        return 0  # WhatsApp-only buys no telephony — no overage exists
    return {"lite": 300, "solo": 500, "clinic": 1_500, "multi": 2_000}.get(plan, 500)


def mandate_max_amount(plan: str, whatsapp_addon: bool = False) -> int:
    """Rupees to authorise on the e-mandate for PLAN.

    Covers: the plan's base, the WhatsApp add-on when the clinic buys it, a
    heavy-but-plausible overage month, and GST headroom — rounded UP to the
    next Rs500 so the figure a clinic signs is a round one.
    """
    p = PLANS.get(plan)
    if not p:
        return 0
    addon = (
        WHATSAPP_ADDON_RUPEES
        if whatsapp_addon and plan in WHATSAPP_ADDON_PLANS
        else 0
    )
    overage = mandate_worst_overage_minutes(plan) * p.overage_per_min
    raw = (p.base_rupees + addon + overage) * MANDATE_GST_HEADROOM
    return int(-(-raw // 500) * 500)  # ceil to the next Rs500
