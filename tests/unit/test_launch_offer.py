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
    effective_price,
    in_offer_window,
)

_NOW = datetime.now(timezone.utc)
_OLD = _NOW - timedelta(days=31 * OFFER_MONTHS + 30)  # well past the window


def test_offer_pricing_first_three_paid_months_then_standard():
    """2026-07-21: acquisition prices apply after trial for three paid months."""
    assert OFFER_PRICES == {"lite": 1_799, "solo": 3_999, "clinic": 6_999, "multi": 11_999}
    assert effective_price("solo", _NOW) == (3_999, True)
    assert effective_price("clinic", _NOW) == (6_999, True)
    assert effective_price("multi", _NOW) == (11_999, True)
    assert effective_price("lite", _NOW) == (1_799, True)
    assert effective_price("solo", _OLD) == (5_999, False)
    assert effective_price("nope", _NOW) == (0, False)


def test_offer_window_machinery_kept():
    # The date window itself is retained (effective_price keys off it); a future
    # offer is a one-line OFFER_PRICES re-add.
    assert in_offer_window(None) is True
    assert in_offer_window(_NOW) is True
    assert in_offer_window(_OLD) is False
    assert in_offer_window(_OLD.replace(tzinfo=None)) is False  # naive-safe


def test_ui_surfaces_show_offer_and_standard_prices():
    """Both price surfaces show acquisition and struck-through list prices."""
    landing = Path("frontend/src/pages/Landing.jsx").read_text(encoding="utf-8")
    static = Path("backend/static/index.html").read_text(encoding="utf-8")
    for text, prices in ((landing, ("₹5,999", "₹9,999", "₹17,999")),
                         (static, ("&#8377;5,999", "&#8377;9,999",
                                   "&#8377;17,999"))):
        for price in prices:
            assert price in text, f"standard price {price} missing"
    for text in (landing, static):
        assert "first 3 paid months" in text
        assert "line-through" in text or "text-decoration:line-through" in text
        assert "₹3,999" in text or "&#8377;3,999" in text


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
        assert "14-day free trial" in landing
        assert "14-day free trial" in static
        assert "trialOn" in landing                 # Landing still guards on live state
    elif _bm.FOUNDING_TRIAL_SLOTS > 0:
        # Capped founding offer: Landing gates on the live count; static stays
        # claim-free because it can't react.
        assert "14-day free trial" in landing
        assert "founding-slots" in landing
        assert "trialOn" in landing
        assert "free trial" not in static.lower()
    else:
        assert "free trial" not in landing.lower()
