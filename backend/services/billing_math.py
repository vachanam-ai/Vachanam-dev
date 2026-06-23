"""Pure billing/unit-economics math for the super-admin console.

Single source of truth for plan pricing (CLAUDE.md — FINAL, change only on
Vinay's instruction) and Vachanam's own cost model. Pure functions: no DB,
no I/O — unit-tested in tests/unit/test_billing_math.py.

All amounts in WHOLE RUPEES (floats only where overage rates demand it).
"""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Plan:
    base_rupees: int
    included_minutes: int
    overage_per_min: float  # rupees


PLANS: dict[str, Plan] = {
    "solo": Plan(1_999, 100, 5.0),
    "clinic": Plan(9_999, 1_800, 5.0),
    "multi": Plan(15_999, 3_600, 5.0),
}

# CLAUDE.md: the 14-day free trial grants a flat 500 voice minutes, regardless
# of the plan the clinic selected at signup. This is the single source of truth.
TRIAL_MINUTES = 500

# Vachanam's own VARIABLE cost floor (CLAUDE.md, 2026-06 repricing): per voice
# minute (Vobiz + Sarvam STT + smallest.ai TTS + Gemini + LiveKit) + DID rent.
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


def next_cycle_start(today: date) -> date:
    """First day of the month AFTER ``today`` — when a clinic-scheduled plan
    change takes effect (never mid-month, so a switch can't shrink the bucket
    the clinic already paid for)."""
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def minutes_exhausted(plan: str, minutes_used: float) -> bool:
    """True when the org has used up its included bucket (hard-block trigger)."""
    inc = included_minutes(plan)
    return inc > 0 and minutes_used >= inc


def call_blocked(
    status: str,
    plan: str,
    hard_block_on_exhaust: bool,
    minutes_used: float,
    trial_ends_at=None,
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
    if hard_block_on_exhaust and minutes_exhausted(plan, minutes_used):
        return "minutes_exhausted"
    return None
