"""WA MVP1 Task 10 — pure validators (no DB, no Meta call).

These map to real Meta rejections we would otherwise surface as an opaque
Graph 400: bad name shape, non-sequential placeholders, a placeholder with
no example value.
"""
import pytest

from backend.services import wa_template_admin


def test_validate_name_rejects_uppercase_and_spaces():
    with pytest.raises(wa_template_admin.TemplateAdminError):
        wa_template_admin.validate_name("Booking Confirm!")


def test_validate_name_rejects_empty():
    with pytest.raises(wa_template_admin.TemplateAdminError):
        wa_template_admin.validate_name("   ")


def test_validate_name_accepts_lowercase_underscored():
    assert wa_template_admin.validate_name("diwali_offer_2026") == "diwali_offer_2026"


def test_validate_body_accepts_no_placeholders():
    assert wa_template_admin.validate_body("Hello there!", []) == []


def test_validate_body_rejects_gap():
    with pytest.raises(wa_template_admin.TemplateAdminError):
        wa_template_admin.validate_body("Hi {{1}} on {{3}}", ["Ravi", "Monday"])


def test_validate_body_rejects_missing_example():
    with pytest.raises(wa_template_admin.TemplateAdminError):
        wa_template_admin.validate_body("Hi {{1}}", [])


def test_validate_body_rejects_blank_example():
    with pytest.raises(wa_template_admin.TemplateAdminError):
        wa_template_admin.validate_body("Hi {{1}}", ["   "])


def test_validate_body_accepts_sequential_with_examples():
    assert wa_template_admin.validate_body(
        "Hi {{1}} on {{2}}. See you soon.", ["Ravi", "Monday"]
    ) == [1, 2]


@pytest.mark.parametrize("body", ["{{1}} is booked.", "Booked for {{1}}"])
def test_validate_body_rejects_placeholder_at_boundary(body):
    with pytest.raises(wa_template_admin.TemplateAdminError):
        wa_template_admin.validate_body(body, ["Monday"])


def test_all_required_and_legacy_system_templates_are_frozen():
    required = {
        item["name"]
        for item in wa_template_admin.SYSTEM_TEMPLATE_DEFINITIONS
    }
    legacy = {
        "booking_confirm", "appt_reminder", "followup", "rating_ask", "leave_rebook",
    }

    assert required == {
        "vachanam_booking_confirm",
        "vachanam_booking_reschedule",
        "vachanam_booking_cancel",
        "vachanam_appt_reminder",
        "vachanam_clinic_location",
        "vachanam_feedback",
        "vachanam_followup",
        "vachanam_rating_ask",
        "vachanam_leave_rebook",
    }
    assert wa_template_admin.SYSTEM_TEMPLATES == required | legacy
