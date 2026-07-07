"""Tests for SENSEX weekly symbol build/decode and premium validation."""

from app.services.bfo_scrip_resolver import build_sensex_weekly_symbol, decode_weekly_symbol_expiry
from app.services.breakout_logic import intrinsic_value, validate_expiry_session_premium


def test_weekly_symbol_jun_25():
    sym = build_sensex_weekly_symbol(77100, "CE", "2026-06-25")
    assert sym == "SENSEX2662577100CE"
    assert decode_weekly_symbol_expiry(sym) == "2026-06-25"


def test_weekly_symbol_jul_2():
    sym = build_sensex_weekly_symbol(77100, "CE", "2026-07-02")
    assert sym == "SENSEX2670277100CE"
    assert decode_weekly_symbol_expiry(sym) == "2026-07-02"


def test_premium_validation_catches_wrong_contract():
    # ITM CE: intrinsic ~37, premium 544 is wrong (July contract on expiry day)
    err = validate_expiry_session_premium("CE", 77100, 77137, 544.75)
    assert err is not None
    assert "inconsistent" in err.lower() or "wrong" in err.lower()


def test_premium_validation_accepts_plausible():
    err = validate_expiry_session_premium("CE", 77100, 77137, 95.60)
    assert err is None


def test_premium_validation_accepts_deep_discount_snapshot():
    err = validate_expiry_session_premium("PE", 76600, 76508.66, 31.65)
    assert err is None
