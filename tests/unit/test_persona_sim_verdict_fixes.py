"""Vinay's line-by-line verdict on the 2026-07-04 persona-sim report
(docs/research/persona-sim-results/2026-07-04-te.md) — each fix below maps to a
transcript line he flagged. Human-gated: these are HIS reviewed changes, not
judge-driven auto-tuning (memory: feedback-no-auto-prompt-tuning).
"""
from pathlib import Path

from agent.i18n.lines import get_lines
from agent.prompts.system_prompt import build_system_prompt

ROOT = Path(__file__).resolve().parents[2]


def _prompt(lang="te"):
    return build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="clinic", language=lang,
    )


def test_complaint_block_apology_first_and_logged():
    """angry_caller overall=2: agent answered a wait-time grievance with the
    off-task redirect and looped one identical line. Complaints get apology
    FIRST, get logged, then ONE open help question."""
    p = _prompt()
    assert "COMPLAINT ABOUT THE CLINIC" in p
    assert "APOLOGISE FIRST" in p
    assert "log_clinic_question" in p
    assert "నేను మీకు ఎలా సహాయపడగలను అండి?" in p
    assert "never repeat a sentence you already said verbatim" in p


def test_offtask_redirect_excludes_clinic_complaints():
    """The rule-5 redirect ("అది నేను చెప్పలేను") is for chit-chat/injection —
    a complaint about THIS clinic is on-task and must never get it."""
    p = _prompt()
    assert "a complaint about THIS clinic" in p.lower() or "complaint about THIS clinic" in p
    assert "NEVER use this redirect line for it" in p


def test_anxious_caller_gets_calm_line_no_medical_opinion():
    """anxious_mother R7=1: booked efficiently, never acknowledged the worry.
    One కంగారు పడకండి line, care-reassurance only, worry acknowledged at close."""
    p = _prompt()
    assert "WORRIED / ANXIOUS" in p
    assert "కంగారు పడకండి" in p
    assert "ZERO medical opinion" in p


def test_urgent_caller_gets_first_slot_directly():
    """"వీలైనంత తొందరగా" got a windows recital + "ఏ టైమ్ వీలవుతుంది?" —
    urgency means offer the FIRST free slot as one yes/no question."""
    p = _prompt()
    assert "వీలైనంత తొందరగా" in p
    assert "FIRST free slot" in p


def test_taken_slot_offers_nearest_not_full_windows():
    """Asked 2 PM (taken, inside hours) → agent recited the full working-hour
    table. Inside hours: offer the NEAREST free time; windows only outside."""
    p = _prompt()
    assert "NEAREST free time" in p
    assert "రెండున్నరకి ఉంది" in p


def test_daypart_mismatch_is_acknowledged():
    """Asked "రేపు మధ్యాహ్నం", got an evening slot with no acknowledgement.
    Nothing free in the asked day-part → say so first, then nearest outside."""
    p = _prompt()
    assert "DAY-PART" in p
    assert "మధ్యాహ్నం ఖాళీ లేదండి" in p


def test_age_question_is_short():
    """"వాళ్ళ వయసు ఎంత ఉంటదండి?" → simply "వయసు ఎంతండి?"."""
    p = _prompt()
    assert 'simply "వయసు ఎంతండి?"' in p


def test_phone_confirm_confusion_gets_detailed_rephrase():
    """Caller confused by the number-confirm question gets the full-detail
    version (booking + reminder calls go to this number) once."""
    p = _prompt()
    assert "రిమైండర్ కాల్స్ కూడా ఆ నంబర్‌కే వస్తాయి" in p


def test_message_leaver_insistence_routes_to_human_transfer():
    """Patients insist on the doctor. Softly ask the matter once; serious
    persistent insistence follows the HUMAN TRANSFER rule."""
    p = _prompt()
    assert "INSIST on speaking to the doctor personally" in p
    assert "that is the HUMAN TRANSFER rule" in p


def test_trailing_off_fragment_is_not_a_turn():
    """"పది గంటలకి... కుదరదేమో." — agent jumped in; the caller was mid-thought
    and finished with the time themselves. Trailing-off = keep listening."""
    p = _prompt()
    assert "TRAILING-OFF" in p
    assert "కుదరదేమో" in p


def test_step0_duplicate_sentence_removed():
    p = _prompt()
    assert p.count("The patient's first reply states what they need.") == 1


def test_warmth_applies_to_every_reply():
    p = _prompt()
    assert "WARMTH IN EVERY REPLY" in p


def test_te_greeting_trimmed_disclosure_intact():
    """R1 "greeting a bit long": drop the redundant మీకు నేను; AI disclosure
    (DPDP s.5) stays. Prompt STEP-0 quote stays in sync with lines.py."""
    g = get_lines("te").disclosure_greeting
    assert g == "నేను ఈ క్లినిక్ ఏఐ అసిస్టెంట్‌ని. చెప్పండి, ఎలా సహాయం చేయగలను?"
    assert g in _prompt()


def test_sim_fake_tools_carry_announce_contract():
    """Sim harness misled the model: fake confirm_booking returned
    token_number 4 with no announce field, so the agent spoke a token number
    for an appointment doctor. Fakes now mirror the prod announce contract."""
    src = (ROOT / "scripts" / "persona_sim.py").read_text(encoding="utf-8")
    assert '"announce": "time_only"' in src
    assert '"token_number": 4' not in src
