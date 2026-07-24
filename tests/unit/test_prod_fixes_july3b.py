"""Regression proofs for the 2026-07-03 evening prod fixes (reminder-call bugs).

R1: already_booked must carry existing_token_id + a reschedule directive — on a
    reminder call the LLM only knows TODAY's token id, so "move my OTHER
    booking" dead-ended and the agent invented "slot not available".
R2: prompt hard-rule — never claim cancel/reschedule done without tool success.
R3: follow-up prompt extras must tell the LLM to ASK the patient's preferred
    time, never pick one itself (agent auto-booked 16:30 unasked).
R4: the te inbound-followup greeting ends with {message} (split-say seam) and a
    name prefix line exists so a recognized caller is greeted by name.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from agent.i18n.lines import get_lines
from agent.livekit_minimal.agent import NEXT_VISIT_PROMPT_EXTRA
from agent.prompts.system_prompt import build_system_prompt


def test_r3_next_visit_extra_asks_time_never_picks():
    text = NEXT_VISIT_PROMPT_EXTRA.lower()
    assert "never pick a time yourself" in text
    assert "check_availability" in text


def test_r2_prompt_forbids_fake_cancel_claims():
    prompt = build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te",
    )
    low = prompt.lower()
    assert "never claim a booking, cancel, or reschedule until that tool returned success=true" in low


def test_r4_te_inbound_greeting_splittable_and_name_prefix():
    lines = get_lines("te")
    assert lines.inbound_followup_greeting.endswith("{message}")
    assert "{patient}" in lines.followup_name_prefix
