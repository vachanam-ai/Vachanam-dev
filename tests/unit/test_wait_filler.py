"""#429 (Vinay 2026-07-20): "for checking and booking appointments and
rescheduling — for tasks it takes some time, say okka nimisham andi ... and it
should not be replying with this phrase for every task. only to the one which
genuinely takes time."

So: a wait-conveying phrase exists per language, it is wired ONLY to the slow
tools (DB + Google Calendar I/O), quick tools stay quiet, and a cooldown stops
one booking flow from saying it twice.
"""
import inspect

from types import SimpleNamespace

import agent.livekit_minimal.agent as agent_mod
from agent.i18n.lines import WAIT_FILLERS, get_wait_fillers
from agent.livekit_minimal.agent import (
    WAIT_FILLER_COOLDOWN_S,
    _say_wait_filler,
)


# ── the phrase itself ────────────────────────────────────────────────────────

def test_wait_fillers_every_language_and_fallback():
    for code in ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn", "or"):
        variants = get_wait_fillers(code)
        assert len(variants) >= 2, code       # not robotic on repeat
        assert all(v.strip() for v in variants), code
    assert len(WAIT_FILLERS) == 9
    assert get_wait_fillers("zz") == get_wait_fillers("te")
    assert get_wait_fillers(None) == get_wait_fillers("te")


def test_wait_phrase_is_a_plain_okay():
    """Vinay 2026-07-20, after hearing the narrated version live: "okka nimisham
    andi feels really bad. change it to okay andi. okay(english). similarly
    hindi version also". The filler is a SHORT okay in every language — the
    slow-tool gating + cooldown convey the wait, not the words."""
    assert get_wait_fillers("te")[0] == "ఓకే అండి."
    assert get_wait_fillers("en")[0] == "Okay."
    assert get_wait_fillers("hi")[0] == "ठीक है।"


def test_wait_phrase_never_narrates_a_wait():
    """The rejected wording must not come back in any language."""
    banned = ("ఒక్క నిమిషం", "ఒక్క సెకను", "One moment", "Just a second",
              "एक मिनट", "एक सेकंड", "checking", "चेक कर")
    for code in ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn", "or"):
        for variant in get_wait_fillers(code):
            for bad in banned:
                assert bad not in variant, (code, variant, bad)


def test_wait_phrase_stays_short():
    # A filler that runs long defeats its purpose (it covers ~1-2s of dead air).
    for code in ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn", "or"):
        for variant in get_wait_fillers(code):
            assert len(variant) <= 16, (code, variant)


# ── played once, then throttled ──────────────────────────────────────────────

class _Sess:
    def __init__(self):
        self.userdata = {"wait_fillers": ("ఒక్క నిమిషం అండి,",), "wait_clips": []}
        self.said = []

    def say(self, text, **kw):
        self.said.append(text)


def test_wait_filler_plays_then_throttles(monkeypatch):
    s = _Sess()
    ctx = SimpleNamespace(session=s)
    _say_wait_filler(ctx)
    assert len(s.said) == 1                    # first slow tool speaks it
    _say_wait_filler(ctx)
    _say_wait_filler(ctx)
    assert len(s.said) == 1                    # same flow stays quiet (#428)


def test_wait_filler_speaks_again_after_cooldown(monkeypatch):
    s = _Sess()
    ctx = SimpleNamespace(session=s)
    _say_wait_filler(ctx)
    assert len(s.said) == 1
    # Rewind the stamp past the cooldown -> a later slow tool may speak again.
    s.userdata["_wait_filler_at"] -= WAIT_FILLER_COOLDOWN_S + 1
    _say_wait_filler(ctx)
    assert len(s.said) == 2


def test_wait_filler_never_raises_on_broken_session():
    _say_wait_filler(SimpleNamespace(session=None))   # must be invisible
    _say_wait_filler(SimpleNamespace())


# ── wiring: slow tools only ──────────────────────────────────────────────────

def _tool_src(name):
    return inspect.getsource(getattr(agent_mod.VachanamAgent, name))


def test_slow_tools_use_the_wait_phrase():
    for tool in ("check_availability", "confirm_booking", "reschedule_booking",
                 "cancel_booking", "find_my_bookings"):
        assert "_say_wait_filler(context)" in _tool_src(tool), tool


def test_quick_tools_do_not_use_the_wait_phrase():
    # assign_token is a Redis INCR — no filler at all.
    src = _tool_src("assign_token")
    assert "_say_wait_filler" not in src
    assert "_say_lookup_filler" not in src
    # route_to_doctor keeps the SHORT ack, not the wait phrase.
    routing = _tool_src("route_to_doctor")
    assert "_say_lookup_filler(context)" in routing
    assert "_say_wait_filler" not in routing


def test_wait_clips_cached_and_reset_on_language_switch():
    entry = inspect.getsource(agent_mod.entrypoint)
    assert 'key="wait_clips"' in entry          # pre-rendered like the acks
    assert '"wait_fillers": get_wait_fillers(lang_code)' in entry
    switch = _tool_src("switch_language")
    assert 'ud["wait_clips"] = []' in switch    # stale-language audio dropped
    assert "get_wait_fillers(code)" in switch
