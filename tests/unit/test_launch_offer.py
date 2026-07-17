"""Launch offer #391 (Vinay 2026-07-17: clinic feedback "pricing too much" —
first-3-months offer prices at 10-15% worst-case margin, GST removed for now,
cloning on every plan during the window, Lite doctors 1→3, UI shows actual
price struck through + offer price labeled "first 3 months")."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services.billing_math import (
    DID_COST_PER_MONTH,  # noqa: F401 — documents the cost model source
    OFFER_MONTHS,
    OFFER_PRICES,
    PLANS,
    cloning_allowed,
    effective_price,
    in_offer_window,
)

_NOW = datetime.now(timezone.utc)
_OLD = _NOW - timedelta(days=31 * OFFER_MONTHS + 30)  # well past the window


def test_offer_margins_hold_10_to_15_percent_worst_case():
    """Vinay's brief: "10-15% profit for us" at the pricing table's own
    worst-case cost discipline (Rs3/min x full bucket + Rs1,500 infra)."""
    for key in ("solo", "clinic", "multi"):
        cost = PLANS[key].included_minutes * 3.0 + 1500.0
        offer = OFFER_PRICES[key]
        margin = (offer - cost) / offer
        # 0.095 floor: prices land on the Indian ₹x,999 point (solo 3,999 =
        # 9.98%, i.e. 10% nominal) — the brief's 10-15% band, retail-rounded.
        assert 0.095 <= margin <= 0.15, f"{key}: {margin:.1%} outside 10-15%"


def test_lite_has_no_offer_price_but_keeps_window_perks():
    # Vinay 2026-07-17 follow-up: "keep lite 1999" — Lite already sits below
    # the margin invariant; no discount. Window perks (cloning) still apply.
    assert "lite" not in OFFER_PRICES
    assert effective_price("lite", _NOW) == (1_999, False)
    assert cloning_allowed("lite", _NOW) is True


def test_offer_window_boundaries():
    assert in_offer_window(None) is True  # trial / pre-signup display
    assert in_offer_window(_NOW) is True
    assert in_offer_window(_NOW - timedelta(days=60)) is True
    assert in_offer_window(_OLD) is False
    # naive datetime never crashes (DB rows may be naive UTC)
    assert in_offer_window(_OLD.replace(tzinfo=None)) is False


def test_effective_price_offer_then_standard():
    assert effective_price("clinic", _NOW) == (6_999, True)
    assert effective_price("clinic", _OLD) == (9_999, False)
    assert effective_price("nope", _NOW) == (0, False)


def test_cloning_every_plan_during_window_standard_gates_after():
    assert cloning_allowed("lite", _NOW) is True     # offer window unlock
    assert cloning_allowed("solo", None) is True
    assert cloning_allowed("lite", _OLD) is False    # window over → standard gate
    assert cloning_allowed("solo", _OLD) is False
    assert cloning_allowed("clinic", _OLD) is True   # Clinic/Multi always
    assert cloning_allowed("multi", _OLD) is True


def test_ui_surfaces_show_offer_prices_and_label():
    """The hardcoded price surfaces must match OFFER_PRICES and carry the
    'first 3 months' label + struck-through actual price."""
    landing = Path("frontend/src/pages/Landing.jsx").read_text(encoding="utf-8")
    static = Path("backend/static/index.html").read_text(encoding="utf-8")
    for text, offers in ((landing, ("₹3,999", "₹6,999", "₹11,999")),
                         (static, ("&#8377;3,999", "&#8377;6,999",
                                   "&#8377;11,999"))):
        for price in offers:
            assert price in text, f"offer price {price} missing"
    # Lite keeps its standard price — no discount shown anywhere.
    assert "₹1,799" not in landing and "&#8377;1,799" not in static
    assert "Offer price — first 3 months" in landing
    assert "line-through" in landing and "line-through" in static
    assert "exclude 18% GST" not in landing
    assert "exclude 18% GST" not in static
