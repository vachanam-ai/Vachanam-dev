"""Pricing display and dormant offer machinery regression tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services.billing_math import (
    DID_COST_PER_MONTH,  # noqa: F401 — documents the cost model source
    OFFER_MONTHS,
    OFFER_PRICES,
    effective_price,
    in_offer_window,
)

_NOW = datetime.now(timezone.utc)
_OLD = _NOW - timedelta(days=31 * OFFER_MONTHS + 30)  # well past the window


def test_every_plan_bills_at_its_list_price():
    """2026-08-04 (Vinay: "remove discount pricings"). No acquisition price,
    from the first paid month — and is_offer False everywhere, so no UI shows
    a struck-through price the invoice will not honour."""
    assert OFFER_PRICES == {}
    assert effective_price("solo", _NOW) == (1_999, False)
    assert effective_price("clinic", _NOW) == (4_999, False)
    assert effective_price("multi", _NOW) == (6_999, False)
    assert effective_price("lite", _NOW) == (1_999, False)
    assert effective_price("solo", _OLD) == (1_999, False)
    assert effective_price("nope", _NOW) == (0, False)


def test_offer_window_machinery_kept():
    # The date window itself is retained (effective_price keys off it); a future
    # offer is a one-line OFFER_PRICES re-add.
    assert in_offer_window(None) is True
    assert in_offer_window(_NOW) is True
    assert in_offer_window(_OLD) is False
    assert in_offer_window(_OLD.replace(tzinfo=None)) is False  # naive-safe


def test_ui_surfaces_show_only_the_list_price():
    """Both price surfaces must quote what the customer is actually charged.
    A struck-through acquisition price left behind after the offer ended would
    advertise a discount billing will not give."""
    landing = Path("frontend/src/pages/Landing.jsx").read_text(encoding="utf-8")
    plans = Path("frontend/src/lib/plans.js").read_text(encoding="utf-8")
    static = Path("backend/static/index.html").read_text(encoding="utf-8")
    for text, prices in ((plans, ("price: 1999", "WHATSAPP_ADDON_RUPEES = 1499")),
                         (static, ("&#8377;1,999", "&#8377;6/voice min",
                                   "&#8377;1,499/month"))):
        for price in prices:
            assert price in text, f"list price {price} missing"
    for text in (landing, plans, static):
        assert "first 3 paid months" not in text
        assert "offer price" not in text.lower()


def test_founding_credit_is_live_gated_and_never_marketed_as_a_trial():
    """#425/#426: the stale '300 free minutes' hero claim may never return.
    Landing free-trial copy must be gated on the LIVE founding-slot count
    (fetch of /auth/founding-slots), so an exhausted offer hides itself; the
    static SEO mirror can't react, so it never claims a trial at all."""
    landing = Path("frontend/src/pages/Landing.jsx").read_text(encoding="utf-8")
    static = Path("backend/static/index.html").read_text(encoding="utf-8")
    # The stale "300 free minutes" claim may never return anywhere.
    assert "300 free minutes" not in landing and "300 free minutes" not in static
    assert "14-day free trial" not in landing.lower()
    assert "14-day free trial" not in static.lower()
    assert "founding-slots" in landing
    assert "foundingOfferOn" in landing
    assert "first {FOUNDING_CREDIT_MINUTES} voice minutes free" in landing
    assert "first 500 voice minutes free" in static.lower()
