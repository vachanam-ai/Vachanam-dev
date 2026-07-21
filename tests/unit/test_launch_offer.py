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
    cloning_allowed,
    effective_price,
    in_offer_window,
)

_NOW = datetime.now(timezone.utc)
_OLD = _NOW - timedelta(days=31 * OFFER_MONTHS + 30)  # well past the window


def test_offer_pricing_removed():
    """#433 (Vinay 2026-07-20: "remove offer pricings"). OFFER_PRICES is now
    empty — every plan is sold at its standard base, is_offer always False."""
    assert OFFER_PRICES == {}
    assert effective_price("solo", _NOW) == (5_999, False)
    assert effective_price("clinic", _NOW) == (9_999, False)
    assert effective_price("multi", _NOW) == (17_999, False)
    assert effective_price("lite", _NOW) == (1_999, False)
    assert effective_price("nope", _NOW) == (0, False)


def test_offer_window_machinery_kept_for_cloning():
    # The date window itself is retained (cloning still keys off it); only the
    # PRICE discount is gone. So a future offer is a one-line OFFER_PRICES re-add.
    assert in_offer_window(None) is True
    assert in_offer_window(_NOW) is True
    assert in_offer_window(_OLD) is False
    assert in_offer_window(_OLD.replace(tzinfo=None)) is False  # naive-safe


def test_cloning_every_plan_during_window_standard_gates_after():
    assert cloning_allowed("lite", _NOW) is True     # offer window unlock
    assert cloning_allowed("solo", None) is True
    assert cloning_allowed("lite", _OLD) is False    # window over → standard gate
    assert cloning_allowed("solo", _OLD) is False
    assert cloning_allowed("clinic", _OLD) is True   # Clinic/Multi always
    assert cloning_allowed("multi", _OLD) is True


def test_ui_surfaces_show_standard_prices_no_offer():
    """#433: the price surfaces show the STANDARD prices only — no
    struck-through 'actual', no 'Offer price — first 3 months' label."""
    landing = Path("frontend/src/pages/Landing.jsx").read_text(encoding="utf-8")
    static = Path("backend/static/index.html").read_text(encoding="utf-8")
    for text, prices in ((landing, ("₹5,999", "₹9,999", "₹17,999")),
                         (static, ("&#8377;5,999", "&#8377;9,999",
                                   "&#8377;17,999"))):
        for price in prices:
            assert price in text, f"standard price {price} missing"
    # The discount and its scaffolding are gone.
    for text in (landing, static):
        assert "Offer price — first 3 months" not in text
        assert "line-through" not in text
        assert "₹3,999" not in text and "&#8377;3,999" not in text


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
