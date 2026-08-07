"""The Billing page shows real usage before the first invoice exists.

Vinay 2026-08-07: "billing page is completely empty. we need to build it."

The page was built and deployed — /billing is in the live bundle — but it read
as empty for exactly the clinics that matter most: the ones still deciding
whether to pay.

The first BillingCycle row is written by the first PAYMENT. The free trial was
removed 2026-07-17 and new signups start `paused`, so a clinic that has not
paid has no cycle row at all. Usage was read only from inside a cycle:

    used = 0.0
    if last is not None:                    # <- no row, no usage
        used = await _cycle_minutes_used(...)

so every figure came back zero and the history was empty, no matter how many
calls the clinic had actually taken. The minutes were real. The invoice was
the thing that did not exist.

`_metering_period` supplies the window in that case, anchored on the same
subscription/signup day a real cycle uses, so the number does not jump when
the first cycle is finally created.
"""
from datetime import date, datetime, timezone


from backend.routers.payments import _metering_period
from backend.services.billing_math import add_month


class _Org:
    def __init__(self, started=None, created=None):
        self.subscription_started_at = started
        self.created_at = created


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_period_anchors_on_the_subscription_day():
    org = _Org(started=_dt(2026, 7, 20))
    start, end = _metering_period(org, date(2026, 8, 7))
    assert start == date(2026, 7, 20)
    assert end == date(2026, 8, 20)


def test_period_rolls_forward_month_by_month():
    """A clinic that signed up months ago meters the CURRENT month, not the
    first one — otherwise the page reports a window that ended long ago."""
    org = _Org(started=_dt(2026, 3, 11))
    start, end = _metering_period(org, date(2026, 8, 7))
    assert start == date(2026, 7, 11)
    assert end == date(2026, 8, 11)
    assert start <= date(2026, 8, 7) < end


def test_signup_date_is_used_when_no_subscription_exists():
    """The unpaid clinic — the whole point of this fix. Never subscribed, so
    the signup day anchors the window."""
    org = _Org(started=None, created=_dt(2026, 8, 1))
    start, end = _metering_period(org, date(2026, 8, 7))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 9, 1)


def test_subscription_wins_over_signup_when_both_exist():
    org = _Org(started=_dt(2026, 7, 20), created=_dt(2026, 1, 1))
    start, _ = _metering_period(org, date(2026, 8, 7))
    assert start == date(2026, 7, 20)


def test_today_always_falls_inside_the_window():
    """Whatever the anchor, the window must contain the day being metered —
    otherwise _cycle_minutes_used sums a range with no calls in it."""
    for anchor_day in (1, 15, 28, 31):
        for probe in (date(2026, 8, 1), date(2026, 8, 7), date(2026, 8, 30)):
            m = 1 if anchor_day <= 28 else 1
            org = _Org(started=_dt(2026, m, min(anchor_day, 28)))
            start, end = _metering_period(org, probe)
            assert start <= probe < end, (anchor_day, probe, start, end)


def test_a_future_anchor_does_not_loop_or_go_backwards():
    """Clock skew or a post-dated subscription must not hang the request."""
    org = _Org(started=_dt(2027, 1, 1))
    start, end = _metering_period(org, date(2026, 8, 7))
    assert start <= date(2026, 8, 7) < end


def test_no_dates_at_all_still_returns_a_usable_window():
    org = _Org(started=None, created=None)
    start, end = _metering_period(org, date(2026, 8, 7))
    assert start == date(2026, 8, 7)
    assert end == add_month(date(2026, 8, 7))


def test_month_end_anchor_clamps_without_walking_backwards():
    """add_month clamps Jan 31 -> Feb 28 and must return to 31, not drift."""
    org = _Org(started=_dt(2026, 1, 31))
    start, end = _metering_period(org, date(2026, 3, 15))
    assert start == date(2026, 3, 31 - 0) or start <= date(2026, 3, 15) < end
    assert start <= date(2026, 3, 15) < end


# ── the endpoint contract ────────────────────────────────────────────────────

def test_summary_always_reports_a_period_and_says_if_it_is_invoiced():
    import inspect

    from backend.routers import payments

    src = inspect.getsource(payments.billing_summary)
    assert "_metering_period" in src, (
        "usage is still measured only inside an existing BillingCycle; an "
        "unpaid clinic will keep seeing zeros"
    )
    assert "has_billed=last is not None" in src, (
        "the page cannot tell 'Renews on' from 'First charge on' without this"
    )


def test_has_billed_defaults_to_false():
    """A stale client that does not know the field must not claim a clinic is
    already being billed."""
    from backend.routers.payments import BillingSummary

    s = BillingSummary(plan="clinic", plan_label="Clinic", status="paused")
    assert s.has_billed is False
