"""Pure billing/unit-economics math for the super-admin console.

Single source of truth for plan pricing (CLAUDE.md — FINAL, change only on
Vinay's instruction) and Vachanam's own cost model. Pure functions: no DB,
no I/O — unit-tested in tests/unit/test_billing_math.py.

All amounts in WHOLE RUPEES (floats only where overage rates demand it).
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass(frozen=True)
class Plan:
    base_rupees: int
    included_minutes: int
    overage_per_min: float  # rupees
    max_doctors: int | None  # None = unlimited
    display_name: str


# Repriced 2026-07-11 (Vinay): every plan holds >=40% gross margin at the
# worst-case full use of its included bucket (cost model: Rs3/min + Rs1,500
# infra/DID per clinic). Internal keys stay solo/clinic/multi (DB enum,
# Razorpay notes, agent cap logic); "Starter" is display-only.
# 2026-07-12 (Vinay): Starter doctor cap 1 → 3. Doctor count is zero-variable-
# cost, so margins are untouched.
# 2026-07-15 (Vinay): NEW entry plan "Lite" (₹1,999) for genuinely low-volume
# clinics that still pay a receptionist full salary. It DELIBERATELY does NOT
# hold the 40%-worst-case invariant the others do — the per-clinic fixed cost
# (DID ₹1,000-1,500/mo) is too large a share of ₹1,999 for that to be possible
# under ₹2k. Vinay accepted the tradeoff: at the TYPICAL cost (₹2/min + ₹1,000
# DID) and its low-volume target, 150 min holds ~35% margin; overage (₹5/min)
# caps the downside (a heavy month pays extra or upgrades). The margin guard
# test carves Lite out explicitly. Follow-up loop IS included (retention).
# 2026-07-17 (Vinay): Lite doctor cap 1 → 3 (zero-variable-cost, same lever
# as Starter's 07-12 bump).
# 2026-08-02 (Vinay): NEW "wa" — WhatsApp-only, no DID, no voice minutes.
# Zero included_minutes/overage is deliberate: the plan buys no telephony at
# all, so an inbound call is a configuration error, not an overage (see
# call_blocked). Spec: docs/superpowers/specs/2026-08-02-whatsapp-pricing-design.md
PLANS: dict[str, Plan] = {
    "wa": Plan(1_499, 0, 0.0, 3, "WhatsApp"),
    "lite": Plan(1_999, 150, 5.0, 3, "Lite"),
    "solo": Plan(5_999, 700, 5.0, 3, "Starter"),
    "clinic": Plan(9_999, 1_500, 5.0, 5, "Clinic"),
    "multi": Plan(17_999, 3_000, 5.0, None, "Multi"),
}

# Fixed monthly cost per clinic, split by whether the plan buys a phone number.
# Until 2026-08-02 this was one flat Rs1,500 constant with the DID folded in —
# which charged a WhatsApp-only clinic for a line it never gets (0*3 + 1500 vs
# a Rs1,499 price = a NEGATIVE margin on our most profitable plan).
DID_RUPEES = 1_200.0  # per-clinic DID; voice plans only
BASE_INFRA = 300.0    # hosting/support share; every plan


def fixed_cost_for(plan: str) -> float:
    """Vachanam's own fixed monthly cost to serve one clinic on this plan."""
    p = PLANS.get(plan)
    has_voice = bool(p and p.included_minutes > 0)
    return (DID_RUPEES + BASE_INFRA) if has_voice else BASE_INFRA

# LAUNCH OFFER (Vinay 2026-07-17 — clinic feedback: "pricing too much; keep it
# low until you get some clients"). For a clinic's FIRST 3 PAID MONTHS:
#   * offer price targets only 10-15% gross margin at the table's own
#     WORST-case cost discipline (Rs3/min x full bucket + Rs1,500 infra/DID):
#     solo 3,999 (10.0%) · clinic 6,999 (14.3%) · multi 11,999 (12.5%).
#     Lite 1,799 CANNOT hold 10% at worst case (fixed DID floor — it already
#     sat below the 40% invariant at Rs1,999, accepted 07-15); ~breakeven at
#     typical cost, flagged to Vinay.
#   * GST not added on top (GST_WAIVED below — "for now remove gst 18%").
# After the window: standard price, standard gates. UI shows the actual price
# struck through + the offer price, labeled "Offer price — first 3 months".
OFFER_MONTHS = 3
# Restored 2026-07-21: after the 14-day trial, the first three paid months use
# an acquisition price. Starter/Clinic/Multi retain 10–15% margin at the
# conservative full-bucket cost model. Lite is the known exception because its
# fixed DID cost makes a 10% worst-case margin impossible below its list price.
OFFER_PRICES: dict[str, int] = {
    "lite": 1_799,
    "solo": 3_999,
    "clinic": 6_999,
    "multi": 11_999,
}


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
FOLLOWUP_PLANS = ("lite", "solo", "clinic", "multi")

# Plans that INCLUDE WhatsApp (confirmations, reminders, rating asks, chat).
# 2026-08-02: "wa" joins clinic/multi — WhatsApp IS that plan. The old note
# "message cost ~Rs0.40/booking, absorbed" is obsolete: under the clinic-owned
# WABA model (spec 2026-08-02-whatsapp-tech-provider) the CLINIC pays Meta
# directly, so our marginal message cost is zero and unmeterable.
WHATSAPP_PLANS = frozenset({"clinic", "multi", "wa"})

# Lite/Starter may BUY WhatsApp for the same Rs1,499 the standalone plan costs
# — one number everywhere, so a clinic never sees it priced two ways. Starter
# + add-on stays under Clinic, which also buys 800 more minutes and 2 more
# doctors, so the upgrade path survives.
WHATSAPP_ADDON_RUPEES = 1_499
WHATSAPP_ADDON_PLANS = frozenset({"lite", "solo"})


def whatsapp_enabled(plan: str, addon: bool = False) -> bool:
    """Single gate for every WhatsApp capability check."""
    return plan in WHATSAPP_PLANS or (bool(addon) and plan in WHATSAPP_ADDON_PLANS)

# The 14-day free trial grants a flat voice-minute bucket regardless of the
# plan picked at signup. 500→300 on 2026-07-11 (Vinay): ~100 calls is enough
# to convince, and the cap is now HARD-enforced for trials in call_blocked
# (trial minutes are Vachanam's own cash — Rs3/min worst case).
TRIAL_MINUTES = 300

# FOUNDING-CLINIC PILOT (Vinay 2026-07-19). Self-serve free trial stays
# REMOVED (signups start paused, 2026-07-17); instead Vinay hand-picks
# clinics and starts a 14-day pilot from the super-admin console. Reuses the
# trial machinery end-to-end: status='trial', TRIAL_MINUTES cap (hard-block),
# trial_ends_at expiry defense in call_blocked, and the 6-hourly trial_pause
# job flips it back to paused — from there the first payment (at launch-offer
# price) activates as usual. Pilot terms (success criteria, auto-convert)
# live on paper, not in code.
PILOT_DAYS = 14

# FOUNDING FREE TRIAL (Vinay 2026-07-20: "add free trail for 14 days for
# first 10 customers. then we can remove."). Self-serve signups get the
# classic 14-day / TRIAL_MINUTES trial back — but only while fewer than
# FOUNDING_TRIAL_SLOTS orgs created on/after FOUNDING_TRIAL_START have ever
# held a trial (trial_ends_at set — admin-granted pilots consume slots too).
# Reuses the whole trial machinery: minute cap in call_blocked, expiry via
# the trial_pause job, first payment activates.
# TO REMOVE THE OFFER: set FOUNDING_TRIAL_SLOTS = 0. Tests then force the
# landing/static free-trial copy to come down too (test_launch_offer).
FOUNDING_TRIAL_SLOTS = 10
FOUNDING_TRIAL_START = datetime(2026, 7, 20, tzinfo=timezone.utc)

# TRIAL FOR ALL (Vinay 2026-07-20: "make 14days free trail common across").
# The founding trial was capped at the first FOUNDING_TRIAL_SLOTS signups;
# now EVERY new clinic gets the 14-day / TRIAL_MINUTES trial. When True, the
# slot count is irrelevant (register grants unconditionally) and the landing
# page advertises the trial to everyone with no scarcity counter. Flip to
# False to fall back to the capped founding-slots behaviour.
TRIAL_FOR_ALL = True

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
VARIABLE_COST_PER_MIN = 2.0
DID_COST_PER_MONTH = 1_000


def month_revenue(plan: str, status: str, minutes_used: float) -> float:
    """Revenue Vachanam earns from this org this month.

    Only ACTIVE orgs pay. Trial = free (cost absorbed); paused/cancelled = no
    billing. Overage charged on minutes beyond the plan's included bucket.
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

    A trial org gets the flat TRIAL_MINUTES bucket regardless of the plan it
    picked at signup; any other status gets the plan's own included bucket.
    Single source for both the clinic dashboard donut and the super-admin view.
    """
    base = TRIAL_MINUTES if status == "trial" else included_minutes(plan)
    return max(0, base + (adjustment or 0))


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
    overage_min = max(0, used - included)
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
) -> dict:
    """What a Razorpay activation/renewal order charges (#341, Vinay 2026-07-12:
    GST ON TOP, overage collected WITH the renewal).

    total = plan base + previous-cycle overage minutes × rate, + GST on the
    whole subtotal (0 while GST_WAIVED). First activation passes
    cycle_minutes_used=0 (trial minutes are free service; exhaust hard-blocks —
    never billed). #391: base honors the first-3-months launch-offer price —
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
    subtotal = round(base + overage_amount, 2)
    gst = _gst_on(subtotal)
    total = round(subtotal + gst, 2)
    return {
        "plan": plan,
        "base": base,
        "is_offer": is_offer,
        "overage_minutes": over_min,
        "overage_amount": overage_amount,
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
    which honors the 500-min trial grant (#166) and the super-admin
    `minutes_adjustment` (#169). Comparing against the plain plan bucket blocked
    trial/adjusted orgs early (e.g. a solo-plan trial cut off at 100 min while
    the donut still showed 400 remaining) and let a negative adjustment block
    later than the dashboard implied.
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
    getting free AI service (~Rs1.49/min cost to Vachanam).
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
    # B3: thread status + adjustment so the hard-block bucket matches the
    # trial grant and super-admin adjustment the dashboard already honors.
    # Trials ALWAYS hard-block on exhaust (2026-07-11): trial minutes are free
    # service at Vachanam's cost — the bucket is the offer, not a suggestion.
    if (hard_block_on_exhaust or status == "trial") and minutes_exhausted(
        plan, minutes_used, status, adjustment
    ):
        return "minutes_exhausted"
    return None
