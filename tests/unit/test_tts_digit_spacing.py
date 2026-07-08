"""#296 (live 2026-07-08 13:46): phone number spoken as "96 crores 66 lakhs".
The LLM emitted the ten digits joined ("9666444428"); the te/en TTS read the
run as one Indian cardinal. _space_digit_runs isolates every digit in the TTS
path so it is always spoken one by one, chunk-split safe."""
from agent.livekit_minimal.agent import _space_digit_runs as spc


def test_ten_digit_phone_spaced():
    assert spc("9666444428") == "9 6 6 6 4 4 4 4 2 8"


def test_number_inside_sentence():
    assert "9 6 6 6 4 4 4 4 2 8" in spc("మీ నంబర్ 9666444428 కరెక్ట్ ఆ?")


def test_single_digit_untouched():
    # a bare "3 o'clock" must NOT be split (it's already one spoken word)
    assert spc("3 గంటలకి") == "3 గంటలకి"


def test_chunk_split_safe():
    # a number split across stream chunks: each half spaced independently,
    # so the concatenation "9 6 6" + "6 4 4 4 4 2 8" is still correct
    assert spc("966") == "9 6 6"
    assert spc("6444428") == "6 4 4 4 4 2 8"


def test_two_digit_run_spaced():
    # even a 2-digit leak ("96") must not read as "ninety-six"
    assert spc("96") == "9 6"


def test_word_digits_untouched():
    assert spc("nine six six six") == "nine six six six"


def test_empty():
    assert spc("") == ""
