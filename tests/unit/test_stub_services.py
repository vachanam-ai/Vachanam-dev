import pytest
from datetime import date, time
from agent.services.calendar_stub import CalendarService
from agent.services.meta_stub import MetaService

@pytest.mark.asyncio
async def test_calendar_stub_returns_fake_event_id():
    cal = CalendarService()
    event_id = await cal.create_booking_event(
        calendar_id="cal@example.com",
        patient_name="Test",
        patient_phone="6789",
        token_number=1,
        booking_date=date.today(),
        appointment_time=None,
        doctor_name="Dr Test",
    )
    assert event_id.startswith("stub-")
    assert len(event_id) == len("stub-") + 36  # uuid4

@pytest.mark.asyncio
async def test_meta_stub_is_noop():
    meta = MetaService()
    result = await meta.send_booking_confirmation(
        to="+919000000000",
        patient_name="Test",
        doctor_name="Dr Test",
        clinic_name="Test Clinic",
        booking_date=date.today(),
        token_number=1,
        appointment_time=None,
    )
    assert result is None
