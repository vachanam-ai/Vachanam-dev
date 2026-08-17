"""Use the clinic's OWN Meta templates, not names we invented.

Vinay 2026-08-04: "i have templates verified in meta. can you fetch them and
use them? i have for confirmation, reschedule, cancellation, sending location
of clinic, feedback after appointment completed."

wa_templates.py hardcodes booking_confirm / appt_reminder / rating_ask /
leave_rebook. Meta rejects a send whose template name it does not know on that
WABA, and under the clinic-owned-WABA model every clinic names its own — so a
hardcoded name is right for at most one clinic and silently wrong for every
clinic onboarded after it.
"""
import pytest

from backend.services import wa_template_registry as reg


def _t(name, status="APPROVED", body="Hi {{1}}, you are booked with {{2}}.", lang="en"):
    return {
        "name": name, "status": status, "language": lang,
        "components": [{"type": "BODY", "text": body}],
    }


# ── picking the right template ───────────────────────────────────────────────

def test_a_clinic_naming_templates_its_own_way_still_works():
    """The whole point: none of these are our canonical names."""
    m = reg.build_map([
        _t("appointment_confirmation"),
        _t("appointment_reschedule"),
        _t("appointment_cancellation"),
        _t("clinic_address_share"),
        _t("post_visit_feedback"),
    ])
    assert m["booking_confirm"]["name"] == "appointment_confirmation"
    assert m["reschedule"]["name"] == "appointment_reschedule"
    assert m["cancel"]["name"] == "appointment_cancellation"
    assert m["location"]["name"] == "clinic_address_share"
    assert m["feedback"]["name"] == "post_visit_feedback"


def test_our_canonical_names_still_win_when_present():
    """A clinic already on our names must not be re-pointed at something else."""
    m = reg.build_map([_t("some_other_confirm"), _t("booking_confirm")])
    assert m["booking_confirm"]["name"] == "booking_confirm"


def test_a_cancellation_template_is_never_used_as_a_confirmation():
    """"booking_cancel_confirmation" contains "confirm". Sending it to someone
    who just booked would tell them their appointment was cancelled."""
    m = reg.build_map([_t("booking_cancel_confirmation")])
    assert m.get("cancel", {}).get("name") == "booking_cancel_confirmation"
    assert "booking_confirm" not in m


@pytest.mark.parametrize("status", ["PENDING", "REJECTED", "PENDING_DELETION", "PAUSED"])
def test_only_approved_templates_are_used(status):
    """Meta refuses to send anything else, so choosing one guarantees failure."""
    m = reg.build_map([_t("appointment_confirmation", status=status)])
    assert m == {}


def test_a_missing_purpose_is_simply_absent():
    """A clinic with no feedback template is not an error — that notification
    is skipped (RULE 4: a notification never fails anything)."""
    m = reg.build_map([_t("appointment_confirmation")])
    assert "feedback" not in m
    assert "booking_confirm" in m


def test_no_templates_at_all_yields_an_empty_map():
    assert reg.build_map([]) == {}


# ── parameter counts ─────────────────────────────────────────────────────────

def test_the_parameter_count_comes_from_the_registered_body():
    m = reg.build_map([_t("appointment_confirmation", body="Hi {{1}}, {{2}} on {{3}} at {{4}}.")])
    assert m["booking_confirm"]["params"] == 4


def test_a_repeated_placeholder_counts_once():
    """Meta counts the highest index, not occurrences."""
    m = reg.build_map([_t("appointment_confirmation", body="{{1}}, see you {{1}} at {{2}}")])
    assert m["booking_confirm"]["params"] == 2


def test_a_template_with_no_variables_reports_zero():
    m = reg.build_map([_t("appointment_confirmation", body="Your appointment is confirmed.")])
    assert m["booking_confirm"]["params"] == 0


def test_the_language_the_clinic_registered_is_carried():
    m = reg.build_map([_t("appointment_confirmation", lang="en_US")])
    assert m["booking_confirm"]["language"] == "en_US"


def test_buttons_are_sent_only_when_the_registered_template_has_them():
    without = _t("appointment_confirmation")
    with_button = _t("vachanam_booking_confirm")
    with_button["components"].append({
        "type": "BUTTONS",
        "buttons": [{"type": "QUICK_REPLY", "text": "Cancel"}],
    })
    assert reg.build_map([without])["booking_confirm"]["buttons"] == 0
    assert reg.build_map([with_button])["booking_confirm"]["buttons"] == 1


# ── fitting our arguments to their template ──────────────────────────────────

def test_extra_arguments_are_dropped_from_the_end():
    """Ours are ordered most- to least-important, so the tail is what goes."""
    assert reg.fit_params(["clinic", "doctor", "when", "map"], 2) == ["clinic", "doctor"]


def test_a_shortfall_is_padded_because_meta_rejects_blanks():
    assert reg.fit_params(["clinic"], 3) == ["clinic", "-", "-"]


def test_an_exact_match_is_unchanged():
    assert reg.fit_params(["a", "b"], 2) == ["a", "b"]


def test_a_template_with_no_variables_takes_no_parameters():
    assert reg.fit_params(["clinic", "doctor"], 0) == []


# ── failure is never an exception ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_branch_with_no_waba_yields_an_empty_map(monkeypatch):
    """RULE 4: a notification path must never raise into a booking."""
    async def boom(branch):
        raise wa_template_registry_error()

    def wa_template_registry_error():
        from backend.services.wa_template_admin import NotConnected

        return NotConnected()

    monkeypatch.setattr(reg.wa_template_admin, "list_templates", boom)
    monkeypatch.setattr(reg, "_cached", lambda *_a, **_k: _none())
    monkeypatch.setattr(reg, "_store", lambda *_a, **_k: _none())

    class _B:
        id = "11111111-1111-1111-1111-111111111111"

    assert await reg.template_map(_B()) == {}


async def _none():
    return None


@pytest.mark.asyncio
async def test_meta_being_down_yields_an_empty_map(monkeypatch):
    async def boom(branch):
        raise RuntimeError("graph 503")

    monkeypatch.setattr(reg.wa_template_admin, "list_templates", boom)
    monkeypatch.setattr(reg, "_cached", lambda *_a, **_k: _none())
    monkeypatch.setattr(reg, "_store", lambda *_a, **_k: _none())

    class _B:
        id = "22222222-2222-2222-2222-222222222222"

    assert await reg.template_map(_B()) == {}


def test_a_reschedule_confirmation_is_not_the_booking_confirmation():
    """"reschedule_confirmed" also contains "confirm"."""
    m = reg.build_map([_t("reschedule_confirmed"), _t("new_booking")])
    assert m["reschedule"]["name"] == "reschedule_confirmed"
    assert m["booking_confirm"]["name"] == "new_booking"


def test_a_reminder_template_is_not_mistaken_for_a_confirmation():
    m = reg.build_map([_t("appointment_reminder_24h")])
    assert m["reminder"]["name"] == "appointment_reminder_24h"
    assert "booking_confirm" not in m


def test_an_exact_canonical_name_wins_even_over_an_exclusion():
    """A clinic that literally names a template booking_confirm has made an
    explicit choice; no heuristic should second-guess it."""
    m = reg.build_map([_t("booking_confirm", body="cancelled {{1}}")])
    assert m["booking_confirm"]["name"] == "booking_confirm"


def test_vinays_five_templates_all_resolve():
    """The set Vinay said he has verified in Meta, in plausible namings."""
    m = reg.build_map([
        _t("appointment_confirmation"),
        _t("appointment_reschedule"),
        _t("appointment_cancellation"),
        _t("clinic_location"),
        _t("appointment_feedback"),
    ])
    assert sorted(m) == ["booking_confirm", "cancel", "feedback", "location", "reschedule"]
