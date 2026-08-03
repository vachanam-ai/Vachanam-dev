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
        "Hi {{1}} on {{2}}", ["Ravi", "Monday"]
    ) == [1, 2]


def test_the_four_system_templates_are_frozen():
    assert wa_template_admin.SYSTEM_TEMPLATES == {
        "booking_confirm", "appt_reminder", "rating_ask", "leave_rebook",
    }
