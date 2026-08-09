"""The date must be in the INSTRUCTIONS, not in trimmable chat history.

Vinay, 2026-08-07, live call: "it is saying todays date as 11 August 2026.
but, its actually 7th August." The same call shows turn 28+ in the Fly logs.

ROOT CAUSE. 538a254 (2026-08-01) fixed exactly this — "the date therefore
rides in the model INSTRUCTIONS, which are sent on every inference and are
never trimmed" — by appending the table inside `build_system_prompt`. But the
live agent never calls `build_system_prompt`; it calls `build_grounded_prompt`
directly and seeds the date into chat history instead. `build_system_prompt`
is reachable only from `agent/eval/`, so the fix landed in the SIMULATOR and
production kept the trimmable layout. The 08-01 verification ("date table
present") measured the sim path.

That is why this file asserts on the function the live agent actually calls.

The second half of the fix is the split: the calendar day goes in the
instructions, the wall clock does not. Instructions are digested into the
prompt-cache key, so a HH:MM inside them would mint a new CachedContent entry
every minute and no call would ever get a cache hit.
"""
import inspect
from datetime import date, datetime

import pytest

from agent.prompts.system_prompt import build_date_context, build_date_table


def test_the_table_carries_no_wall_clock():
    """A clock in the instructions re-keys the prompt cache every minute."""
    table = build_date_table(date(2026, 8, 7))
    assert "TODAY IS Friday, 07 August 2026" in table
    assert "current time" not in table
    assert ":" not in table.split("DATE LOOKUP")[0]


def test_the_table_is_stable_for_a_whole_day():
    """Same calendar day -> byte-identical -> one cache entry per day."""
    morning = build_date_table(datetime(2026, 8, 7, 6, 0).date())
    midnight = build_date_table(datetime(2026, 8, 7, 23, 59).date())
    assert morning == midnight


def test_the_table_re_keys_at_midnight():
    assert build_date_table(date(2026, 8, 7)) != build_date_table(date(2026, 8, 8))


def test_build_date_context_still_carries_the_clock():
    """The runtime block keeps the time; only its home changed."""
    ctx = build_date_context(datetime(2026, 8, 7, 15, 50))
    assert "TODAY IS Friday, 07 August 2026" in ctx
    assert "current time 15:50" in ctx


def test_todays_row_cannot_be_mistaken_for_another_row():
    """"11 August" was a real row in the table the model was reading."""
    table = build_date_table(date(2026, 8, 7))
    assert "today Friday = 2026-08-07" in table
    assert "2026-08-11" in table          # the date it wrongly announced
    assert "TODAY IS Friday, 07 August 2026" in table


# ── the live path, not the simulator ─────────────────────────────────────────

def test_the_live_instructions_builder_appends_the_date_table():
    """`_compose_instructions` is what becomes the model's instructions. If the
    table is not added THERE, the date exists only in the seeded first history
    message — the first thing trimmed on a long call.

    2026-08-09: the live path now delegates to `compose_clinic_instructions`
    (one composer, so the warmer and the call cannot drift apart again — that
    drift cost 16 uncached turns on Vinay's benchmark call). The property is
    unchanged and still asserted; it just lives one level down now, so this
    checks BOTH that the live site supplies the day and that the composer uses
    it."""
    from agent.livekit_minimal import agent as agent_mod
    from agent.livekit_minimal.agent import compose_clinic_instructions

    src = inspect.getsource(agent_mod.entrypoint)
    compose = src.split("def _compose_instructions")[1].split("def _compose_runtime_context")[0]
    assert "today=" in compose, (
        "the live prompt no longer passes a calendar day; the model will guess "
        "today's date as soon as the seeded history block is trimmed"
    )
    assert "build_date_table" in inspect.getsource(compose_clinic_instructions), (
        "the shared composer dropped the date table — every caller loses it"
    )

def test_the_runtime_block_does_not_duplicate_the_table():
    """It sits outside the cache, so a second copy is paid for on every turn."""
    from agent.livekit_minimal import agent as agent_mod

    src = inspect.getsource(agent_mod.entrypoint)
    assert "date_context = build_date_context(now_b)" not in src


@pytest.mark.parametrize("name", ["build_date_table"])
def test_agent_imports_what_it_uses(name):
    from agent.livekit_minimal import agent as agent_mod

    assert hasattr(agent_mod, name)
