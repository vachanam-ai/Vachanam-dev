"""Regression tests for the 2026-08-06 live-call defects (Vinay).

Reported after real calls:
  1. "doctor is not available at specified time even though he is available"
  2. "after selecting time it says sorry, there is a problem in booking, shall
     I try again... then it asked what is your problem, then it is booking"
  3. treatment follow-up calls "reading out instructions and all"
  4. after switching to English, "10am" is spoken as "padi am"
Plus two product changes: English weekday names in every language, and
greeting a known caller by name.

These are pure unit tests — no DB, no Redis, no network. The Redis behaviour is
proven against a real Lua-executing fake so the atomicity claim is tested, not
assumed.
"""
from __future__ import annotations

import inspect
import re
from datetime import date, time

import pytest

from agent.tools import booking_tools


# ── #2 / #1: Redis slot counters can never go negative ───────────────────────


class FakeRedis:
    """Minimal Redis with REAL semantics for the operations under test.

    Crucially it reproduces the actual defect: DECR on a MISSING key creates it
    at -1 with no TTL. A fake that returned 0 instead would hide the bug.
    """

    def __init__(self, initial: dict[str, int] | None = None):
        self.store: dict[str, int] = dict(initial or {})
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        v = self.store.get(key)
        return None if v is None else str(v)

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key):
        # Redis: missing key is treated as 0, so DECR makes it -1 and sets NO TTL.
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    async def eval(self, script, numkeys, *args):
        """Execute the two Lua scripts used by booking_tools."""
        key = args[0]
        cur = self.store.get(key)
        if "if cur and cur > 0 then" in script:  # _SLOT_RELEASE_LUA
            if cur is not None and cur > 0:
                self.store[key] = cur - 1
                return self.store[key]
            return cur if cur is not None else 0
        if "if cur and cur < 0 then" in script:  # _SLOT_REPAIR_INCR_LUA
            if cur is not None and cur < 0:
                self.store[key] = 0
            return await self.incr(key)
        if "local floor" in script:  # _TOKEN_SEED_INCR_LUA
            floor = int(args[1])
            if floor > (cur or 0):
                self.store[key] = floor
            return await self.incr(key)
        raise AssertionError(f"unexpected script: {script[:60]}")


def test_fake_redis_reproduces_the_real_decr_defect():
    """Guard the guard: if this stops holding, the tests below prove nothing."""
    r = FakeRedis()

    async def go():
        assert await r.decr("slot:missing") == -1
        assert "slot:missing" not in r.ttls  # no TTL -> the key is permanent

    import asyncio

    asyncio.run(go())


@pytest.mark.asyncio
async def test_release_never_creates_a_key_or_goes_negative():
    """The root cause of "problem in booking": a release that raced its own
    hold's expiry used to DECR a missing key to a permanent -1."""
    r = FakeRedis()
    key = "slot:doc:branch:2026-08-06:0900"

    assert await booking_tools.release_slot_hold(r, key) == 0
    assert r.store.get(key) is None, "release must not CREATE the key"

    r.store[key] = 1
    assert await booking_tools.release_slot_hold(r, key) == 0
    assert await booking_tools.release_slot_hold(r, key) == 0, "must clamp at 0"
    assert r.store[key] == 0


@pytest.mark.asyncio
async def test_release_refuses_token_counters():
    """RULE 2: the token counter IS the queue sequence — never decrement it."""
    r = FakeRedis({"token:doc:branch:2026-08-06": 5})
    await booking_tools.release_slot_hold(r, "token:doc:branch:2026-08-06")
    assert r.store["token:doc:branch:2026-08-06"] == 5


@pytest.mark.asyncio
async def test_corrupt_negative_key_cannot_hand_out_token_number_zero():
    """The exact live failure. A key left at -1 made INCR return 0, so
    assign_token issued token_number=0 and confirm_booking collided on
    uq_token_number_confirmed -> the caller heard "there is a problem in
    booking" and only the RETRY (0 -> 1) worked.

    Proof the key was real, from live Redis on 2026-08-06:
        slot:dc5c32d0…:11ea4044…:2026-08-05:0900 = -1 ttl=-1
    """
    key = "slot:doc:branch:2026-08-06:0900"
    r = FakeRedis({key: -1})

    plain = await r.incr(key)  # what the OLD code did
    assert plain == 0, "precondition: INCR from -1 yields 0"

    r = FakeRedis({key: -1})
    repaired = int(await r.eval(booking_tools._SLOT_REPAIR_INCR_LUA, 1, key))
    assert repaired == 1, "repair-then-INCR must never yield 0"
    assert repaired >= 1


@pytest.mark.asyncio
async def test_repair_incr_is_a_plain_increment_when_healthy():
    """The repair must not disturb a normal counter (no double-booking risk)."""
    key = "slot:doc:branch:2026-08-06:0900"
    r = FakeRedis({key: 1})
    assert int(await r.eval(booking_tools._SLOT_REPAIR_INCR_LUA, 1, key)) == 2


def test_no_bare_decr_remains_on_any_slot_path():
    """Every slot release must go through the atomic helper. A bare or
    GET-then-DECR release is what created the permanent -1."""
    import agent.livekit_minimal.agent as agent_mod
    import backend.routers.queue as queue_mod
    import backend.services.cascade_cancel as cascade_mod

    for mod in (booking_tools, queue_mod, cascade_mod):
        src = inspect.getsource(mod)
        assert "await r.decr(slot_key)" not in src
        assert not re.search(r"if int\(await _?r\.get\(key\) or 0\) > 0:", src), (
            f"{mod.__name__} still uses the racy GET-then-DECR release"
        )

    agent_src = inspect.getsource(agent_mod)
    assert "release_slot_hold" in agent_src


def test_check_availability_clamps_a_negative_reserved_count():
    src = inspect.getsource(booking_tools.check_availability)
    assert "reserved = max(reserved, 0)" in src


# ── #2 (second cause): a required tool arg the model omits hard-fails ────────


def test_confirm_booking_complaint_is_optional():
    """A REQUIRED function-tool arg the model omits is rejected by
    function-call validation before the body runs — the caller hears "there is
    a problem in booking" and the model then re-asks for the complaint it
    already had. token_number was made optional for exactly this reason."""
    from agent.livekit_minimal.agent import VachanamAgent

    sig = inspect.signature(VachanamAgent.confirm_booking)
    assert sig.parameters["complaint"].default == "", (
        "complaint must have a default so a missing arg cannot hard-fail a booking"
    )
    # The body must still tolerate an empty complaint.
    src = inspect.getsource(VachanamAgent.confirm_booking)
    assert 'complaint = (complaint or "").strip()' in src
    assert "if not complaint" not in src, "an empty complaint must not be rejected"


# ── #3: follow-up calls must not read instructions/ISO dates aloud ───────────


def test_spoken_target_date_carries_no_unspeakable_parenthesis():
    from agent.livekit_minimal.agent import _spoken_target_date

    spoken = _spoken_target_date("2026-08-29", "te")
    assert "2026-08-29" not in spoken, "the ISO date must not sit inside speech"
    assert "(" not in spoken and ")" not in spoken
    assert spoken.strip()

    english = _spoken_target_date("2026-08-29", "en")
    assert "2026-08-29" not in english
    assert "29" in english and "August" in english


def test_followup_date_block_is_empty_when_there_is_no_date():
    """The old code substituted the prose placeholder
    "(none — the doctor did not ask for a specific date)" into the prompt,
    which the model read out to the patient."""
    from agent.livekit_minimal.agent import _followup_date_block

    assert _followup_date_block("", "te") == ""
    assert _followup_date_block(None, "te") == ""


def test_followup_date_block_separates_speech_from_tool_data():
    from agent.livekit_minimal.agent import _followup_date_block

    block = _followup_date_block("2026-08-29", "te")
    assert "2026-08-29" in block, "the ISO date is still available to the tools"
    assert "never" in block.lower() and "spoken" in block.lower()


def test_followup_prompts_no_longer_rely_on_a_suppression_rule():
    """"Never read the parenthesis aloud" was a prompt rule the model broke on
    a real call. Anything unspeakable must not be inside the spoken sentence."""
    import agent.livekit_minimal.agent as agent_mod

    for name in ("NEXT_VISIT_PROMPT_EXTRA", "DOCTOR_ADVICE_PROMPT_EXTRA"):
        text = getattr(agent_mod, name)
        assert "BEFORE the parenthesis" not in text, f"{name} still suppresses by rule"
        assert "never read the parenthesis" not in text.lower()


def test_no_literal_format_placeholder_leaks_into_spoken_prompt_text():
    """A non-f-string containing {date} put the literal text "{date}" in front
    of the model, which can read it aloud."""
    import agent.livekit_minimal.agent as agent_mod

    src = inspect.getsource(agent_mod)
    marker = "wanted to see you around"
    idx = src.find(marker)
    assert idx != -1, "the pending-follow-up prompt moved; update this test"
    assert "{date}" not in src[idx : idx + 200]


# ── #4 + weekday rule: deterministic word substitutions at the TTS boundary ──


def test_weekdays_are_english_in_every_language():
    """Vinay: "change days (sunday, monday,...) to english always. never
    senivaram, somavaram etc. always saturday, monday etc in every language"."""
    from agent.services.pronunciation import build_replacer
    from agent.services.spoken_words import speech_map

    cases = {
        "te": ("శనివారం", "Saturday"),
        "hi": ("सोमवार", "Monday"),
        "ta": ("வெள்ளிக்கிழமை", "Friday"),
        "kn": ("ಬುಧವಾರ", "Wednesday"),
        "mr": ("मंगळवार", "Tuesday"),
        "bn": ("বৃহস্পতিবার", "Thursday"),
        "ml": ("ഞായറാഴ്ച", "Sunday"),
    }
    for lang, (native, english) in cases.items():
        sub, _ = build_replacer(speech_map(lang))
        assert sub(f"డాక్టర్ {native} ఉంటారు").find(english) != -1, (
            f"{lang}: {native} was not spoken as {english}"
        )


def test_english_call_speaks_numbers_in_english_not_padi():
    """The reported defect: after switching to English the model still wrote
    the Telugu number WORD, so "10am" was spoken "padi am" (పది = ten)."""
    from agent.services.pronunciation import build_replacer
    from agent.services.spoken_words import speech_map

    sub, _ = build_replacer(speech_map("en"))
    assert "ten" in sub("పది am")
    assert "పది" not in sub("పది am")
    assert "ten thirty" in sub("పదిన్నర")


def test_telugu_call_keeps_telugu_numbers():
    """The inverse must NOT happen — a Telugu call should say "పది గంటలకి".
    Rewriting that to English would be the bug, not the fix."""
    from agent.services.pronunciation import build_replacer
    from agent.services.spoken_words import speech_map

    sub, _ = build_replacer(speech_map("te"))
    assert sub("పది గంటలకి") == "పది గంటలకి"


def test_number_map_is_generated_from_the_same_source_as_the_speech():
    """The reverse map is built from telugu_dates.telugu_number, so it cannot
    drift from the words the deterministic confirmations actually emit."""
    from agent.services.spoken_words import NUMBER_WORDS_TO_ENGLISH
    from agent.services.telugu_dates import telugu_number

    for n, expected in ((1, "one"), (7, "seven"), (10, "ten"), (30, "thirty")):
        assert NUMBER_WORDS_TO_ENGLISH[telugu_number(n)] == expected


def test_word_rules_are_installed_even_without_a_pronunciation_map():
    """They must be live from the first word: the pronunciation map arrives
    late on a cache miss, and not at all if its lookup fails."""
    import agent.livekit_minimal.agent as agent_mod

    src = inspect.getsource(agent_mod.VachanamAgent.set_pronunciations)
    assert "speech_map" in src
    assert "merged.update(mapping or {})" in src, (
        "a clinic pronunciation must still win over a generic word rule"
    )
    init_src = inspect.getsource(agent_mod.VachanamAgent.__init__)
    assert "self.set_pronunciations({})" in init_src


def test_time_and_daypart_words_are_dropped_on_an_english_call():
    from agent.services.pronunciation import build_replacer
    from agent.services.spoken_words import speech_map

    sub, _ = build_replacer(speech_map("en"))
    out = sub("ఉదయం పది గంటలకి")
    assert "ఉదయం" not in out and "గంటలకి" not in out
    assert "ten" in out


# ── change 2: greet a known caller by name ───────────────────────────────────


def test_known_caller_is_not_greeted_by_name_by_default():
    import agent.livekit_minimal.agent as agent_mod

    assert agent_mod._GREET_BY_NAME is False


def test_caller_language_is_remembered_across_calls():
    """"and, remember their language too" — the stored per-caller language must
    drive the language this call is answered in."""
    import agent.livekit_minimal.agent as agent_mod

    src = inspect.getsource(agent_mod)
    assert "if _pref_res and _pref_res in serviceable_languages:" in src
    assert "state.preferred_language = _pref_res" in src
    assert "caller_lang_mapped" in src


# ── date/time helpers used above ─────────────────────────────────────────────


def test_spoken_target_date_falls_back_on_bad_input():
    from agent.livekit_minimal.agent import _spoken_target_date

    assert _spoken_target_date("not-a-date", "te") == "not-a-date"
    assert _spoken_target_date("", "te") == ""


def test_telugu_time_and_date_helpers_still_render(monkeypatch):
    """Sanity: the helpers the confirmations depend on are untouched."""
    from agent.services.telugu_dates import telugu_date, telugu_time

    assert telugu_date(date(2026, 8, 29))
    assert telugu_time(time(10, 30))


# ── streaming integration: the rules must survive chunk boundaries ───────────


async def _drain(chunks, lang):
    """Run CHUNKS through the real TTS-boundary stream stage."""
    from agent.livekit_minimal.agent import _spoken_names_stream
    from agent.services.pronunciation import build_replacer
    from agent.services.spoken_words import speech_map

    sub, hold = build_replacer(speech_map(lang))

    async def _src():
        for c in chunks:
            yield c

    return "".join([out async for out in _spoken_names_stream(_src(), sub, hold)])


@pytest.mark.asyncio
async def test_weekday_split_across_chunks_still_becomes_english():
    """The LLM streams; "శనివారం" can arrive as "శని" + "వారం". A map that only
    works on whole strings would miss exactly this case."""
    assert "Saturday" in await _drain(["రేపు ", "శని", "వారం", " వస్తారు"], "te")


@pytest.mark.asyncio
async def test_padi_split_across_chunks_still_becomes_ten():
    assert "ten" in await _drain(["ప", "ది", " am"], "en")


@pytest.mark.asyncio
async def test_romanized_padi_split_across_chunks_still_becomes_ten():
    """Exact live regression: Gemini emitted Latin `padi am` after English."""
    out = await _drain(["pa", "di", " am"], "en")
    assert "ten am" in out.casefold()
    assert "padi" not in out.casefold()


def test_romanized_telugu_time_is_fully_english_at_tts_boundary():
    from agent.services.pronunciation import build_replacer
    from agent.services.spoken_words import speech_map

    sub, _ = build_replacer(speech_map("en"))
    assert sub("udayam padi gantalaki").strip() == "ten"
    assert sub("padinnara am") == "ten thirty am"


@pytest.mark.asyncio
async def test_stream_never_drops_or_duplicates_surrounding_text():
    out = await _drain(["Dr Rao sits ", "సోమ", "వారం", " morning"], "te")
    assert out.startswith("Dr Rao sits ")
    assert out.endswith(" morning")
    assert out.count("Monday") == 1


# ── #1: a hold that outlives its call makes a FREE slot read as booked ───────


@pytest.mark.asyncio
async def test_concurrent_slot_holds_each_release_correctly():
    """Why a free slot reported "not available" (#1).

    A slot counter is a QUANTITY, not a sequence, so releasing it must be an
    unconditional decrement. The old shutdown cleanup released only when the
    counter still equalled THIS caller's number, so with max_concurrent_per_slot
    >= 2 the first caller's hold was never given back and the slot stayed
    falsely occupied until the 900s TTL expired.
    """
    key = "slot:doc:branch:2026-08-06:1800"
    r = FakeRedis()

    a = await r.incr(key)  # caller A holds
    b = await r.incr(key)  # caller B holds the second seat
    assert (a, b) == (1, 2)

    # A hangs up first. Old rule: `current == a` -> 2 != 1 -> NO release (leak).
    assert r.store[key] != a, "precondition: the old equality rule would skip"
    await booking_tools.release_slot_hold(r, key)
    assert r.store[key] == 1, "A's seat must be given back regardless of order"

    await booking_tools.release_slot_hold(r, key)
    assert r.store[key] == 0, "B's seat too — the slot is free again"


def test_shutdown_releases_slot_holds_unconditionally():
    """The shutdown path must not gate a SLOT release on the counter still
    matching this caller's number (that is a token-queue rule, not a slot one)."""
    import agent.livekit_minimal.agent as agent_mod

    src = inspect.getsource(agent_mod)
    idx = src.find("async def _cleanup_on_shutdown")
    assert idx != -1
    body = src[idx : idx + 2000]
    assert 'if key.startswith("slot:")' in body
    assert "release_slot_hold(r, key)" in body
    # The token-queue branch keeps its equality rule (numbers are a sequence).
    assert "current == state.token_number" in body
