"""Guard natural time speech and deterministic phone-number rendering."""
from agent.prompts.system_prompt import build_system_prompt


def test_prompt_fences_say_without_do():
    # #415 real call: "చెక్ చేస్తున్నాను… వెయిట్ చేయండి" then a minute of silence —
    # the lookup tool was never called. The fence orders the tool call in the
    # SAME turn as any "checking/wait" phrasing.
    p = build_system_prompt("ఆరోగ్య", [], "", "clinic", language="te")
    assert "SAYING IS NOT DOING" in p
    assert "SAME turn" in p and "find_my_bookings" in p


def test_prompt_never_sends_caller_back_to_clinic():
    # #418 real call: caller ASKED the clinic's own AI line for info and was told
    # "confirm at the clinic". Unknown info = log_clinic_question + "we'll check
    # with the doctor and get back" — never a pointer back to the clinic.
    p = build_system_prompt("ఆరోగ్య", [], "", "clinic", language="te")
    assert "say they can confirm at the clinic" not in p
    assert "THIS call IS the clinic" in p
    assert "log_clinic_question in the SAME turn" in p
    assert "డాక్టర్ గారిని అడిగి చెప్పిస్తాను" in p


def test_prompt_keeps_times_natural_and_phone_digits_clear():
    p = build_system_prompt("ఆరోగ్య", [], "", "clinic", language="te")
    compact = " ".join(p.split())
    assert "Times, dates, ages, fees, tokens: natural spoken numbers" in p
    assert "Add a day-part when a time would be ambiguous" in p
    assert "PLAIN DIGITS" in p
    assert "never English number words inside another language" in compact
