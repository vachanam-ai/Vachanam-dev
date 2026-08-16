"""Generated regression matrix for hidden WhatsApp booking identity state."""
from datetime import date, timedelta
from itertools import product
from uuid import NAMESPACE_URL, uuid5

from backend.services.wa_agent import (
    _remember_tool_result,
    _verified_booking_context,
)


def test_6720_verified_booking_contexts_survive_message_boundaries():
    languages = ("en", "te", "hi", "ta", "kn", "ml", "mr", "bn")
    doctors = ("Lakshmi", "Srinivas", "Vishnu", "Karishma", "Narayana")
    dates = tuple((date(2026, 8, 17) + timedelta(days=i)).isoformat() for i in range(7))
    times = ("9 am", "10 am", "11:45 am", "12 pm", "5:30 pm", "8:45 pm")
    patients = ("self", "child", "parent", "spouse")

    checked = 0
    for language, doctor, day, at_time, patient in product(
        languages, doctors, dates, times, patients
    ):
        appointment_id = str(uuid5(
            NAMESPACE_URL, f"{language}:{doctor}:{day}:{at_time}:{patient}"
        ))
        row = {
            "appointment_id": appointment_id,
            "patient": patient,
            "doctor": doctor,
            "date": day,
            "time": at_time,
        }
        draft = _remember_tool_result(
            {}, "my_appointments", {}, {"appointments": [row]}
        )
        context = _verified_booking_context(draft)
        assert draft["appointments"] == [row]
        assert appointment_id in context
        assert doctor in context and day in context and at_time in context
        assert "never show IDs to the patient" in context
        checked += 1

    assert checked == 6720


def test_existing_booking_creates_exact_pending_reschedule_and_success_clears_it():
    appointment_id = str(uuid5(NAMESPACE_URL, "existing-booking"))
    draft = _remember_tool_result(
        {},
        "book_appointment",
        {"doctor_name": "Lakshmi", "date": "2026-08-17", "time": "12:45"},
        {
            "success": False,
            "existing_appointment_id": appointment_id,
            "existing_time": "10 am",
        },
    )
    assert draft["pending"] == {
        "action": "reschedule",
        "appointment_id": appointment_id,
        "doctor": "Lakshmi",
        "date": "2026-08-17",
        "time": "12:45",
    }
    assert _remember_tool_result(
        draft, "reschedule_appointment", {}, {"success": True}
    ) == {}


def test_empty_database_result_clears_stale_booking_state():
    stale = {
        "appointments": [{"appointment_id": "stale"}],
        "pending": {"action": "reschedule", "appointment_id": "stale"},
    }
    assert _remember_tool_result(
        stale, "my_appointments", {}, {"appointments": []}
    ) == {}
