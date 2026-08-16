"""The WhatsApp add-on: a voice clinic buys chat independently.

Spec: docs/superpowers/specs/2026-08-02-whatsapp-pricing-design.md §1.

Found in production 2026-08-03: a real clinic on `solo` messaged the pilot
number and every message was dropped with `wa_skipped_plan`, because WhatsApp
was bundled only into clinic/multi/wa. That is the correct billing behaviour
and the wrong product behaviour — the add-on is how a Starter clinic pays for
it. Without this, the only route was upgrading to Clinic (+₹4,000/mo) or
misstating the org's plan.

The flag lives on the BRANCH, not the org: WhatsApp is provisioned per number
(each branch has its own WABA and its own Meta billing), so an org with three
branches genuinely needs three numbers and three add-ons.
"""
from types import SimpleNamespace

from backend.services.billing_math import (
    PLANS,
    WHATSAPP_ADDON_PLANS,
    WHATSAPP_ADDON_RUPEES,
    whatsapp_enabled,
)


def _branch(addon: bool = False):
    return SimpleNamespace(
        id="b1", wa_phone_number_id="111", wa_token_enc=None,
        wa_status="connected", whatsapp_addon=addon,
    )


# ── the gate itself ──────────────────────────────────────────────────────────

def test_addon_turns_whatsapp_on_for_every_voice_plan():
    for plan in ("lite", "solo", "clinic", "multi"):
        assert whatsapp_enabled(plan, addon=False) is False
        assert whatsapp_enabled(plan, addon=True) is True


def test_addon_cannot_conjure_whatsapp_onto_an_unknown_plan():
    assert whatsapp_enabled("", addon=True) is False
    assert whatsapp_enabled("nonsense", addon=True) is False


def test_whatsapp_plan_bundles_whatsapp():
    assert whatsapp_enabled("wa", addon=False) is True


def test_addon_and_standalone_prices_are_explicit():
    assert WHATSAPP_ADDON_RUPEES == 1499
    assert PLANS["wa"].base_rupees == 1999
    assert WHATSAPP_ADDON_PLANS == frozenset({"lite", "solo", "clinic", "multi"})


# ── wa_service.wa_enabled must honour it (this is the production path) ───────

def test_wa_enabled_reads_the_branch_addon_flag(monkeypatch):
    """The regression that started this: a `solo` branch with the add-on must
    pass the gate that logged `wa_skipped_plan` in production."""
    from backend.services import wa_service

    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    assert wa_service.wa_enabled(_branch(addon=False), "solo") is False
    assert wa_service.wa_enabled(_branch(addon=True), "solo") is True


def test_current_growth_plan_requires_the_addon(monkeypatch):
    from backend.services import wa_service

    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    assert wa_service.wa_enabled(_branch(addon=True), "clinic") is True
    assert wa_service.wa_enabled(_branch(addon=False), "clinic") is False


def test_a_branch_without_the_attribute_is_treated_as_no_addon(monkeypatch):
    """Defensive: an ORM object loaded before the column existed, or a stub in
    a test, must not accidentally grant a paid feature."""
    from backend.services import wa_service

    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    bare = SimpleNamespace(
        id="b1", wa_phone_number_id="111", wa_token_enc=None, wa_status="connected",
    )
    assert wa_service.wa_enabled(bare, "solo") is False


def test_addon_does_not_grant_voice(monkeypatch):
    """The add-on buys WhatsApp only. It must never affect call gating —
    a Starter clinic with the add-on still has exactly its own minutes."""
    from backend.services.billing_math import call_blocked

    assert call_blocked("active", "solo", True, 0) is None
    assert call_blocked("active", "solo", True, 10_000) is None
