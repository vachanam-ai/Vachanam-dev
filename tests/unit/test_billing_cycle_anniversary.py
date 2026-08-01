"""Included minutes run from the day the clinic PAID to that same day next
month — never the calendar 1st (Vinay live 2026-08-01: "call minutes getting
reset on 1st of every month. it should be from payment done date to next month
same date").

The old gate metered `started_at >= replace(day=1)`, so a clinic that paid on
the 20th got a brand-new bucket 11 days later — free minutes every month, and
the hard block never fired when it should have.
"""
from datetime import date

import pytest

from backend.services.billing_math import add_month, cycle_window


# --------------------------------------------------------------------------
# add_month — same day-of-month, with real-calendar clamping
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "anchor,expected",
    [
        (date(2026, 8, 1), date(2026, 9, 1)),
        (date(2026, 8, 20), date(2026, 9, 20)),
        (date(2026, 1, 15), date(2026, 2, 15)),
        (date(2026, 12, 20), date(2027, 1, 20)),  # year rollover
        (date(2026, 12, 31), date(2027, 1, 31)),  # December edge
    ],
)
def test_add_month_keeps_the_same_day(anchor, expected):
    assert add_month(anchor) == expected


@pytest.mark.parametrize(
    "anchor,expected",
    [
        (date(2026, 1, 31), date(2026, 2, 28)),  # 2026 is not a leap year
        (date(2024, 1, 31), date(2024, 2, 29)),  # leap year
        (date(2026, 3, 31), date(2026, 4, 30)),  # 31 -> 30-day month
        (date(2026, 5, 31), date(2026, 6, 30)),
    ],
)
def test_short_months_clamp_to_the_last_real_day(anchor, expected):
    assert add_month(anchor) == expected


def test_clamping_never_walks_the_billing_day_backwards():
    """A 31st payer must bill on the 31st again after February — the clamp is
    computed from the ORIGINAL anchor, not from the previous clamped date.
    (Chaining add_month(add_month(x)) would drift 31 -> 28 -> 28 forever.)"""
    anchor = date(2026, 1, 31)
    days = [add_month(anchor, n).day for n in range(0, 13)]
    assert days[1] == 28  # February clamps
    assert days[2] == 31  # March returns to the 31st
    assert days[3] == 30  # April clamps
    assert days[12] == 31  # a full year later, still the 31st


def test_add_month_supports_going_backwards():
    assert add_month(date(2026, 8, 20), -1) == date(2026, 7, 20)
    assert add_month(date(2026, 1, 20), -1) == date(2025, 12, 20)


# --------------------------------------------------------------------------
# cycle_window — the window metering must use
# --------------------------------------------------------------------------
def test_the_first_of_the_month_does_not_reset_the_bucket():
    """THE REPORTED BUG. Paid 20 July; on 1 August the clinic is still inside
    the 20 Jul -> 20 Aug cycle, so its used minutes must NOT reset."""
    anchor = date(2026, 7, 20)

    start, end = cycle_window(anchor, date(2026, 8, 1))

    assert (start, end) == (date(2026, 7, 20), date(2026, 8, 20))
    assert start.day != 1


def test_window_rolls_only_on_the_anniversary_day():
    anchor = date(2026, 7, 20)

    # day before renewal -> still the old cycle
    assert cycle_window(anchor, date(2026, 8, 19))[0] == date(2026, 7, 20)
    # renewal day -> new cycle starts, inclusive
    assert cycle_window(anchor, date(2026, 8, 20)) == (
        date(2026, 8, 20),
        date(2026, 9, 20),
    )


def test_window_contains_today_and_is_half_open():
    anchor = date(2026, 3, 5)
    for probe in (date(2026, 3, 5), date(2026, 3, 20), date(2026, 4, 4)):
        start, end = cycle_window(anchor, probe)
        assert start <= probe < end, probe


def test_window_is_exactly_one_month_long_every_month_for_a_year():
    anchor = date(2026, 1, 31)
    for months in range(12):
        probe = add_month(anchor, months)
        start, end = cycle_window(anchor, probe)
        assert start == probe
        assert end == add_month(anchor, months + 1)


def test_old_calendar_month_behaviour_is_gone():
    """Guard against a regression back to `replace(day=1)`."""
    anchor = date(2026, 7, 20)
    start, _ = cycle_window(anchor, date(2026, 8, 15))
    assert start != date(2026, 8, 1)
    assert start == date(2026, 7, 20)


def test_anchor_in_the_future_does_not_explode():
    anchor = date(2026, 9, 10)
    start, end = cycle_window(anchor, date(2026, 8, 1))
    assert start < end
    assert end == anchor


def test_thirty_day_cycles_would_have_drifted():
    """Why same-day beats `+ timedelta(days=30)`: 30-day cycles slide the
    billing day earlier every month, so the renewal date stops matching the
    date the clinic actually paid."""
    from datetime import timedelta

    anchor = date(2026, 1, 31)
    thirty = anchor + timedelta(days=30)
    assert thirty == date(2026, 3, 2)  # skips February entirely
    assert add_month(anchor) == date(2026, 2, 28)
