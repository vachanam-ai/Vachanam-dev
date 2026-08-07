"""The cache warmer must compose the SAME instructions a call composes.

Vinay 2026-08-08: "reading date very wrongly. saying monday is august 11, but
its august 10. why?"

11 August was a Monday in 2025. That answer is the model reciting a calendar
from its training data, which is what it does when the date table is not in
front of it — and the table itself is correct, verified for 2026-08-08:

    today Saturday = 2026-08-08
    tomorrow Sunday = 2026-08-09
    Monday = 2026-08-10

What was wrong is that EVERY call ran uncached. The prompt cache key is a
sha256 of the instructions string, and there are two places that build it:

    _compose_instructions        grounded + date_table + brevity   (live call)
    _warm_all_clinic_prompt_caches  grounded + brevity             (warmer)

#491 moved the date table into the instructions and updated only the first.
From that moment the warmer minted entries under a digest no call could ever
ask for: the warming was wasted and `prompt_cached_tokens` was 0 on every turn
in production. This codebase already has a recorded case of uncached runs
hallucinating rather than following the prompt.

The two compositions have to stay byte-identical, so this asserts on the
composition rather than on any one symptom.
"""
import inspect

from agent.livekit_minimal import agent as agent_mod


def _live_src() -> str:
    src = inspect.getsource(agent_mod.entrypoint)
    return src.split("def _compose_instructions")[1].split("def _compose_runtime_context")[0]


def _warmer_src() -> str:
    return inspect.getsource(agent_mod._warm_all_clinic_prompt_caches)


def test_the_warmer_includes_the_date_table():
    assert "build_date_table" in _warmer_src(), (
        "the warmer builds instructions without the date table, so its digest "
        "can never match a live call's — every call runs uncached"
    )


def test_the_live_path_includes_the_date_table():
    assert "build_date_table" in _live_src()


def test_both_compositions_use_the_same_pieces():
    """Any piece present in one and absent from the other changes the digest
    and silently disables the cache."""
    live, warm = _live_src(), _warmer_src()
    for piece in ("build_grounded_prompt", "build_date_table", "brevity"):
        assert piece in live, f"live composition lost {piece}"
        assert piece in warm, f"warmer composition lost {piece}"


def test_the_cache_key_is_a_digest_of_the_instructions():
    """This is WHY the two must agree — the key is derived from the text."""
    src = inspect.getsource(agent_mod._prompt_cache_key)
    assert "sha256" in src
    assert "instructions" in src


def test_the_cache_key_carries_the_date():
    """The table is only safe to cache because the key rolls over at midnight;
    without this a stale 'today' would be served all the next day."""
    assert "Asia/Kolkata" in inspect.getsource(agent_mod._prompt_cache_key)


def test_the_warmer_dates_in_the_same_timezone_as_the_key():
    """A warmer on UTC would disagree with the key's IST date for 5.5 hours
    every night, re-breaking the match after midnight."""
    assert "Asia/Kolkata" in _warmer_src()


def test_the_warmer_imports_what_it_uses():
    """ZoneInfo is not module-level here; a missing local import would raise
    inside the warmer's own try/except and look like an ordinary warm failure."""
    warm = _warmer_src()
    if "ZoneInfo" in warm:
        assert "from zoneinfo import ZoneInfo" in warm
