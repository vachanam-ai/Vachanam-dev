"""#296 (live 2026-07-08): 10-digit phone spoken as "96 crores 66 lakhs" —
long digit runs must be spaced so TTS reads them digit-by-digit.
#333 (live 2026-07-12): the same spacing shredded short numbers too — date
"13" came out "ఒకటి మూడు" (okati moodu) instead of "పదమూడు" (padamoodu).
Contract now: runs of 5+ digits spaced (phones, OTP-like); 1-4 digit runs
(dates, tokens, times, years) left joined. Chunk-split phones stay safe via
the trailing-digit carry in _space_digits_stream."""
import asyncio

from agent.livekit_minimal.agent import _normalize_times
from agent.livekit_minimal.agent import _space_digit_runs as spc
from agent.livekit_minimal.agent import _space_digits_stream


def _stream(chunks):
    async def gen():
        for c in chunks:
            yield c

    async def collect():
        return "".join([c async for c in _space_digits_stream(gen())])

    return asyncio.run(collect())


def test_ten_digit_phone_spaced():
    assert spc("9666444428") == "9 6 6 6 4 4 4 4 2 8"


def test_phone_inside_sentence():
    assert "9 6 6 6 4 4 4 4 2 8" in spc("మీ నంబర్ 9666444428 కరెక్ట్ ఆ?")


def test_date_day_not_spaced():
    # THE #333 bug: "13" must reach TTS joined so it's read "పదమూడు"
    assert spc("జులై 13 కి రండి") == "జులై 13 కి రండి"


def test_token_time_year_not_spaced():
    assert spc("టోకెన్ 23") == "టోకెన్ 23"
    assert spc("11:30") == "11:30"
    assert spc("2026") == "2026"


def test_five_digit_run_spaced():
    assert spc("12345") == "1 2 3 4 5"


def test_single_digit_untouched():
    assert spc("3 గంటలకి") == "3 గంటలకి"


def test_word_digits_untouched():
    assert spc("nine six six six") == "nine six six six"


def test_empty():
    assert spc("") == ""


def test_chunk_split_phone_still_spaced():
    # phone cut across stream chunks is stitched back into one 10-digit run
    out = _stream(["మీ నంబర్ 96664", "44428 కరెక్ట్ ఆ?"])
    assert "9 6 6 6 4 4 4 4 2 8" in out


def test_chunk_split_date_not_spaced():
    out = _stream(["జులై 1", "3 కి రండి"])
    assert "జులై 13 కి రండి" in out


def test_trailing_digits_flushed_at_stream_end():
    assert _stream(["టోకెన్ 2", "3"]) == "టోకెన్ 23"
    assert _stream(["9666444428"]) == "9 6 6 6 4 4 4 4 2 8"


def test_on_the_hour_time_reads_as_hour():
    # "10:00 AM" was read "one zero zero zero am" — must become "10 AM"
    assert _normalize_times("రేపు 10:00 AM కి రండి") == "రేపు 10 AM కి రండి"
    assert _stream(["రేపు 10:00 AM కి"]) == "రేపు 10 AM కి"


def test_half_hour_time_reads_hour_minute():
    assert _normalize_times("4:30 PM") == "4 30 PM"


def test_chunk_split_time_still_normalized():
    assert _stream(["సాయంత్రం 10:", "00 కి"]) == "సాయంత్రం 10 కి"


def test_time_normalization_never_touches_phone():
    assert _stream(["మీ నంబర్ 9666444428"]) == "మీ నంబర్ 9 6 6 6 4 4 4 4 2 8"
