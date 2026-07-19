"""Guard the time-speaking contract. History: RULE 6 originally banned Latin
AM/PM AND clock digits (agent said "9:30 AM", TTS spelled it). #408 (Vinay
2026-07-19, real call: time spoken as Telugu "ఆరున్నర") FLIPPED the digits
half: the model now WRITES digits ("6:30") and the deterministic TTS-boundary
converter (tts_sanitizer.spoken_english_numbers) speaks them as ENGLISH words
("six thirty") in every language. AM/PM stays banned — the native day-part
word (సాయంత్రం…) carries meridiem."""
from agent.prompts.system_prompt import build_system_prompt


def test_prompt_fences_say_without_do():
    # #415 real call: "చెక్ చేస్తున్నాను… వెయిట్ చేయండి" then a minute of silence —
    # the lookup tool was never called. The fence orders the tool call in the
    # SAME turn as any "checking/wait" phrasing.
    p = build_system_prompt("ఆరోగ్య", [], "", "clinic", language="te")
    assert "SAYING IS NOT DOING" in p
    assert "SAME turn" in p and "find_my_bookings" in p


def test_prompt_requires_digit_times_english_speech():
    p = build_system_prompt("ఆరోగ్య", [], "", "clinic", language="te")
    # AM/PM still banned
    assert '"AM"' in p and '"PM"' in p
    # #408: digits required, native number words banned
    assert "NUMBERS ARE ALWAYS DIGITS" in p
    assert "ఆరున్నర" in p  # shown as the banned example
    assert "six thirty" in p
    # day-part word stays native around the digits
    assert "సాయంత్రం 6:30 కి" in p
