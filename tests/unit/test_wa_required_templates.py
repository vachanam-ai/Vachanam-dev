"""Required templates and sender semantics cannot drift independently."""
from backend.services import wa_template_admin, wa_template_registry


def _meta_row(spec):
    body = {"type": "BODY", "text": spec["body"]}
    return {
        "name": spec["name"],
        "language": "en",
        "status": "APPROVED",
        "components": [body],
    }


def test_required_templates_cover_every_patient_event():
    mapping = wa_template_registry.build_map([
        _meta_row(spec) for spec in wa_template_admin.SYSTEM_TEMPLATE_DEFINITIONS
    ])
    assert set(mapping) == {
        "booking_confirm", "reschedule", "cancel",
        "location", "feedback", "followup", "reminder", "rating", "leave_rebook",
    }
    assert mapping["booking_confirm"]["params"] == 6
    assert mapping["reschedule"]["params"] == 4
    assert mapping["cancel"]["params"] == 4
    assert mapping["reminder"]["params"] == 5


def test_time_sensitive_templates_tell_patient_to_arrive_on_time():
    specs = {s["name"]: s for s in wa_template_admin.SYSTEM_TEMPLATE_DEFINITIONS}
    for name in (
        "vachanam_booking_confirm",
        "vachanam_booking_reschedule",
        "vachanam_appt_reminder",
    ):
        assert "Please come on time." in specs[name]["body"]


def test_cli_installer_uses_the_same_required_definitions():
    from scripts.wa_create_templates import TEMPLATES

    assert {item["name"] for item in TEMPLATES} == {
        item["name"] for item in wa_template_admin.SYSTEM_TEMPLATE_DEFINITIONS
    }
