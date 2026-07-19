"""#408 (Vinay 2026-07-19, real call): every digit the agent speaks is ENGLISH
WORDS, always — phone one-by-one ("eight zero nine six…"), time "six thirty",
age "forty eight" — never Telugu/Hindi number words, in ANY call language.
Supersedes the #296/#333 digit-SPACING contract: spaced digits still came out
in the session language ("ఎనిమిది సున్నా…"). Conversion is deterministic at the
TTS boundary (tts_sanitizer.spoken_english_numbers), wired into BOTH the
streaming tts_node (_space_digits_stream) and sanitize_for_tts (say() paths).
Also #408: Hindi TTS clipped "डॉक्टर" to "doc" — phonetic "डाक्टर" speaks full.
History: #296 "96 crores", #333 "ఒకటి మూడు" for 13 — both still guarded, now
via English words."""
import asyncio

from agent.livekit_minimal.agent import _space_digits_stream
from agent.services.tts_sanitizer import sanitize_for_tts, spoken_english_numbers as eng


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield c

    async def collect():
        return "".join([c async for c in _space_digits_stream(gen())])

    return asyncio.run(collect())


def test_ten_digit_phone_english_one_by_one():
    # THE 2026-07-19 bug: 8096007554 was spoken "ఎనభై తొమ్మిది అరవై సున్నా…"
    assert eng("8096007554") == "eight zero nine six zero zero seven five five four"


def test_phone_inside_telugu_sentence():
    out = eng("మీ నంబర్ 9666444428 కరెక్ట్ ఆ?")
    assert "nine six six six four four four four two eight" in out
    assert "9666444428" not in out


def test_time_english_words():
    assert eng("6:30") == "six thirty"
    assert eng("10:00") == "ten"
    assert eng("9:05") == "nine oh five"
    assert eng("18:30") == "six thirty"     # 24h clock → 12h words
    assert eng("12:15") == "twelve fifteen"


def test_age_and_small_numbers_english():
    assert eng("వయసు 48") == "వయసు forty eight"
    assert eng("టోకెన్ 23") == "టోకెన్ twenty three"
    assert eng("జులై 13 కి రండి") == "జులై thirteen కి రండి"
    assert eng("3 గంటలకి") == "three గంటలకి"


def test_year_cardinal():
    assert eng("2026") == "two thousand twenty six"


def test_word_digits_untouched():
    assert eng("nine six six six") == "nine six six six"


def test_hindi_doctor_phonetic():
    # TTS clipped डॉक्टर to "doc"; phonetic डाक्टर speaks the full word
    assert eng("आपको डॉक्टर करिश्मा देखेंगी") == "आपको डाक्टर करिश्मा देखेंगी"
    assert sanitize_for_tts("डॉक्टर करिश्मा") == "डाक्टर करिश्मा"


def test_empty():
    assert eng("") == ""


def test_sanitize_for_tts_applies_english_numbers():
    assert sanitize_for_tts("మీ టైమ్ 6:30, వయసు 48") == "మీ టైమ్ six thirty, వయసు forty eight"


def test_chunk_split_phone_still_english():
    out = _stream(["మీ నంబర్ 96664", "44428 కరెక్ట్ ఆ?"])
    assert "nine six six six four four four four two eight" in out


def test_chunk_split_time_still_english():
    assert _stream(["సాయంత్రం 10:", "00 కి"]) == "సాయంత్రం ten కి"
    assert _stream(["సాయంత్రం 6:", "30 కి"]) == "సాయంత్రం six thirty కి"


def test_trailing_digits_flushed_at_stream_end():
    assert _stream(["టోకెన్ 2", "3"]) == "టోకెన్ twenty three"
    assert _stream(["8096007554"]) == "eight zero nine six zero zero seven five five four"
