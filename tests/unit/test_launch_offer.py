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
    assert effective_price("solo", _NOW) == (5_999, False)
    assert effective_price("clinic", _NOW) == (10_999, False)
    assert effective_price("multi", _NOW) == (21_999, False)
    assert effective_price("lite", _NOW) == (1_999, False)
    assert effective_price("solo", _OLD) == (5_999, False)
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
    for text, prices in ((plans, ("price: 5999", "price: 10999", "price: 21999")),
                         (static, ("&#8377;5,999", "&#8377;10,999",
                                   "&#8377;21,999"))):
        for price in prices:
            assert price in text, f"list price {price} missing"
    for text in (landing, plans, static):
        assert "first 3 paid months" not in text
        assert "offer price" not in text.lower()


def test_no_free_trial_claims_on_landing():
    """#425/#426: the stale '300 free minutes' hero claim may never return.
    Landing free-trial copy must be gated on the LIVE founding-slot count
    (fetch of /auth/founding-slots), so an exhausted offer hides itself; the
    static SEO mirror can't react, so it never claims a trial at all."""
    landing = Path("frontend/src/pages/Landing.jsx").read_text(encoding="utf-8")
    static = Path("backend/static/index.html").read_text(encoding="utf-8")
    # The stale "300 free minutes" claim may never return anywhere.
    assert "300 free minutes" not in landing and "300 free minutes" not in static
    from backend.services import billing_math as _bm
    if getattr(_bm, "TRIAL_FOR_ALL", False):
        # #433: trial is universal, so BOTH surfaces advertise it (the static
        # mirror can safely claim it — every clinic qualifies, no counter).
        assert "14 days" in landing
        assert "14-day free trial" in static
        assert "trialOn" in landing                 # Landing still guards on live state
    elif _bm.FOUNDING_TRIAL_SLOTS > 0:
        # Capped founding offer: Landing gates on the live count; static stays
        # claim-free because it can't react.
        assert "14 days" in landing
        assert "founding-slots" in landing
        assert "trialOn" in landing
        assert "free trial" not in static.lower()
    else:
        assert "free trial" not in landing.lower()
