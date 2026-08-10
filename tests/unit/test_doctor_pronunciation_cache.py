"""Doctor names and roles must be SPOKEN in the call language's script, from a
per-clinic per-language cache (Vinay 2026-08-01: "name pronunciation of doctors
and their roles is very important ... extract them and store them as cache ...
so we can directly speak and pronunciation also remains intact").

Soniox voices text by SCRIPT: Latin "Dr. Srinivas" inside a Telugu sentence is
read with an English accent. The substitution happens at the TTS boundary only,
so the LLM and every tool still see the original Latin name (doctor matching and
tool arguments are untouched).
"""
import asyncio

import pytest

from agent.livekit_minimal.agent import _spoken_names_stream
from agent.services.pronunciation import (
    _generate,
    build_replacer,
    cache_key,
    needs_conversion,
    normalize_pronunciation_mapping,
    roster_digest,
)

_MAP = {
    "Dr. Srinivas": "డాక్టర్ శ్రీనివాస్",
    "Srinivas": "శ్రీనివాస్",
    "Dental": "దంత వైద్యులు",
}


async def _drain(chunks, sub, hold):
    return "".join([c async for c in _spoken_names_stream(_agen(chunks), sub, hold)])


async def _agen(items):
    for i in items:
        yield i


def _run(chunks, mapping=_MAP):
    sub, hold = build_replacer(mapping)
    return asyncio.run(_drain(chunks, sub, hold))


# --------------------------------------------------------------------------
# replacement correctness
# --------------------------------------------------------------------------
def test_latin_name_is_spoken_in_native_script():
    out = _run(["Dr. Srinivas is available at 5 PM"])
    assert "డాక్టర్ శ్రీనివాస్" in out
    assert "Srinivas" not in out


def test_role_is_also_converted():
    out = _run(["Dental checkup"])
    assert "దంత వైద్యులు" in out


def test_longest_key_wins_over_a_shorter_one():
    """"Dr. Srinivas" must not be replaced as "Dr. " + the bare-name mapping."""
    out = _run(["Dr. Srinivas"])
    assert out == "డాక్టర్ శ్రీనివాస్"


def test_name_split_across_chunks_is_still_replaced():
    out = _run(["Book with Dr. Srin", "ivas please"])
    assert "డాక్టర్ శ్రీనివాస్" in out


def test_no_text_is_ever_lost_or_duplicated():
    """The transform may under-replace, but it must never corrupt the reply."""
    chunks = ["Hello ", "there, ", "your token ", "is 12."]
    assert _run(chunks) == "Hello there, your token is 12."


def test_name_inside_a_longer_word_is_not_touched():
    out = _run(["Srinivasan"], {"Srinivas": "శ్రీనివాస్"})
    assert out == "Srinivasan"


def test_empty_map_passes_text_through_untouched():
    sub, hold = build_replacer({})
    assert sub is None
    assert asyncio.run(_drain(["Dr. Srinivas at 5"], sub, hold)) == "Dr. Srinivas at 5"


def test_matching_is_case_insensitive():
    assert "శ్రీనివాస్" in _run(["dr. srinivas"], {"Dr. Srinivas": "శ్రీనివాస్"})


@pytest.mark.parametrize("chunking", [
    ["Dr. Srinivas"],
    ["Dr.", " Srinivas"],
    ["D", "r", ".", " ", "S", "r", "i", "n", "i", "v", "a", "s"],
])
def test_replacement_is_chunk_boundary_independent(chunking):
    assert _run(chunking) == "డాక్టర్ శ్రీనివాస్"


# --------------------------------------------------------------------------
# cache identity
# --------------------------------------------------------------------------
def test_cache_key_is_per_clinic_and_per_language():
    d = roster_digest([("Dr. Srinivas", "Dental")])
    assert cache_key("branch-a", "te", d) != cache_key("branch-b", "te", d)
    assert cache_key("branch-a", "te", d) != cache_key("branch-a", "hi", d)


def test_bad_cached_bare_name_cannot_add_a_second_doctor_honorific():
    mapping = normalize_pronunciation_mapping(
        {"Srinivas": "డాక్టర్ శ్రీనివాస్"}
    )
    assert mapping == {"Srinivas": "శ్రీనివాస్"}
    sub, _ = build_replacer(mapping)
    spoken = sub("డాక్టర్ Srinivas")
    assert spoken == "డాక్టర్ శ్రీనివాస్"
    assert spoken.count("డాక్టర్") == 1


def test_stored_honorific_is_preserved_once():
    mapping = normalize_pronunciation_mapping(
        {"Dr. Srinivas": "డాక్టర్ శ్రీనివాస్"}
    )
    assert mapping == {"Dr. Srinivas": "డాక్టర్ శ్రీనివాస్"}


@pytest.mark.asyncio
async def test_generated_bare_name_is_sanitized(monkeypatch):
    async def fake_call(_prompt):
        return '[{"name":"డాక్టర్ శ్రీనివాస్","role":"దంత వైద్యులు"}]'

    monkeypatch.setattr("agent.services.pronunciation._call_gemini", fake_call)
    result = await _generate([("Srinivas", "Dental")], "te")
    assert result["Srinivas"] == "శ్రీనివాస్"


def test_same_roster_reuses_the_same_cache_entry():
    """"they remain same across" — an unchanged roster must not regenerate."""
    a = roster_digest([("Dr. Srinivas", "Dental"), ("Dr. Lakshmi", "Skin")])
    b = roster_digest([("Dr. Srinivas", "Dental"), ("Dr. Lakshmi", "Skin")])
    assert a == b


def test_changing_a_doctor_or_role_busts_the_cache():
    base = roster_digest([("Dr. Srinivas", "Dental")])
    assert roster_digest([("Dr. Srinivas", "Skin")]) != base
    assert roster_digest([("Dr. Lakshmi", "Dental")]) != base
    assert roster_digest([("Dr. Srinivas", "Dental"), ("Dr. X", "Skin")]) != base


# --------------------------------------------------------------------------
# when to convert at all
# --------------------------------------------------------------------------
def test_english_calls_need_no_conversion():
    assert needs_conversion("Dr. Srinivas", "en") is False


def test_already_native_script_needs_no_conversion():
    assert needs_conversion("డాక్టర్ శ్రీనివాస్", "te") is False


def test_latin_name_on_a_telugu_call_needs_conversion():
    assert needs_conversion("Dr. Srinivas", "te") is True
