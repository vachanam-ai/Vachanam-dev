"""build_date_context: the LLM must look up weekday→date, not compute it.

Regression for the off-by-one bug (caller said Tuesday, agent booked Wednesday).
"""
from datetime import datetime

from agent.prompts.system_prompt import build_date_context


def test_weekday_maps_to_correct_date():
    # Saturday 2026-06-20 → Tuesday is the 23rd, NOT the 24th (the bug).
    ctx = build_date_context(datetime(2026, 6, 20, 15, 50))
    assert "Tuesday = 2026-06-23" in ctx
    assert "Tuesday = 2026-06-24" not in ctx
    assert "today Saturday = 2026-06-20" in ctx
    assert "tomorrow Sunday = 2026-06-21" in ctx
    assert "TODAY IS Saturday, 20 June 2026" in ctx


def test_table_covers_eight_days_and_forbids_calculation():
    ctx = build_date_context(datetime(2026, 6, 20, 9, 0))
    # one row per day, today..today+7
    for iso in ("2026-06-20", "2026-06-21", "2026-06-25", "2026-06-27"):
        assert iso in ctx
    assert "NEVER calculate a date yourself" in ctx
