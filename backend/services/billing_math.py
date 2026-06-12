"""Pure billing/unit-economics math for the super-admin console.

Single source of truth for plan pricing (CLAUDE.md — FINAL, change only on
Vinay's instruction) and Vachanam's own cost model. Pure functions: no DB,
no I/O — unit-tested in tests/unit/test_billing_math.py.

All amounts in WHOLE RUPEES (floats only where overage rates demand it).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    base_rupees: int
    included_minutes: int
    overage_per_min: float  # rupees


PLANS: dict[str, Plan] = {
    "solo": Plan(1_999, 100, 3.0),
    "clinic": Plan(7_999, 2_100, 3.0),
    "multi": Plan(16_999, 4_200, 2.5),
}

# Vachanam's own cost floor (CLAUDE.md): variable per voice minute + DID rent.
VARIABLE_COST_PER_MIN = 1.49
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


def minutes_exhausted(plan: str, minutes_used: float) -> bool:
    """True when the org has used up its included bucket (hard-block trigger)."""
    inc = included_minutes(plan)
    return inc > 0 and minutes_used >= inc


def call_blocked(status: str, plan: str, hard_block_on_exhaust: bool, minutes_used: float) -> str | None:
    """Why an incoming call for this org must NOT be served, or None.

    Returns 'paused' | 'cancelled' | 'minutes_exhausted' | None. The voice
    agent must still ANSWER and speak one polite line (RULE 8 — never dead
    air), then hang up.
    """
    if status in ("paused", "cancelled"):
        return status
    if hard_block_on_exhaust and minutes_exhausted(plan, minutes_used):
        return "minutes_exhausted"
    return None
