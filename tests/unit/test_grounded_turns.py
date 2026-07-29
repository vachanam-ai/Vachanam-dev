from datetime import date, time

from agent.livekit_minimal.confirm_speech import build_confirm_text
from agent.livekit_minimal.grounded_turns import (
    doctor_roster_reply,
    extract_exact_time,
    is_short_close_reply,
)
from agent.prompts.system_prompt import DoctorContext


def _roster():
    return [
        DoctorContext(
            id="1", name="Dr. Lakshmi", specialization="Skin Specialist",
            routing_keywords=[], booking_type="appointment", is_default=False,
        ),
        DoctorContext(
            id="2", name="Vishnu", specialization="children specialist",
            routing_keywords=[], booking_type="appointment", is_default=False,
        ),
        DoctorContext(
            id="3", name="Dr. Srinivas", specialization="Dental",
            routing_keywords=[], booking_type="appointment", is_default=False,
        ),
    ]


def test_skin_doctor_is_answered_from_roster_without_unknown_promise():
    reply = doctor_roster_reply("is there any skin doctor with you?", "te", _roster())
    assert "Dr. Lakshmi" in reply
    assert "అవునండి" in reply
    assert "అడిగి" not in reply


def test_absent_orthopedic_is_plainly_denied_from_roster():
    reply = doctor_roster_reply("is there any orthopedic doctor?", "te", _roster())
    assert "లేరండి" in reply
    assert "ఆ స్పెషాలిటీ డాక్టర్ మా దగ్గర లేరు" in reply
    assert "అడిగి" not in reply


def test_doctor_list_is_grounded_but_normal_booking_turn_is_not_hijacked():
    reply = doctor_roster_reply("what doctors do you have?", "en", _roster())
    assert all(name in reply for name in ("Dr. Lakshmi", "Vishnu", "Dr. Srinivas"))
    assert doctor_roster_reply("I need a doctor appointment tomorrow", "te", _roster()) is None


def test_exact_time_correction_inherits_prior_evening_period():
    assert extract_exact_time("no, I said 7", time(19, 30)) == time(19, 0)
    assert extract_exact_time("ఏడు గంటలకి", time(19, 30)) == time(19, 0)
    assert extract_exact_time("ఏడున్నరకి", time(19, 0)) == time(19, 30)
    assert extract_exact_time("7:15 pm", time(9, 0)) == time(19, 15)


def test_unrelated_long_number_sentence_is_not_treated_as_a_time():
    assert extract_exact_time("the patient is 7 years old", time(19, 30)) is None
    assert extract_exact_time("Lakshmi 7", time(19, 30)) is None


def test_new_booking_confirmation_offers_more_help_but_cancel_does_not():
    booked = build_confirm_text(
        "te", "booked_slot", date_=date(2026, 7, 30), time_=time(19, 0)
    )
    assert "టైంకి రండి" in booked
    assert "ఇంకేమైనా సహాయం చేయనా" in booked
    cancelled = build_confirm_text("te", "cancelled")
    assert "ఇంకేమైనా" not in cancelled


def test_post_booking_close_requires_an_unambiguous_short_reply():
    assert is_short_close_reply("No, thanks")
    assert is_short_close_reply("అంతే")
    assert not is_short_close_reply("No, I need another appointment")
