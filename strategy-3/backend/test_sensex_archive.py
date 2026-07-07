"""Tests for SENSEX historical instrument archive."""

from app.services.bfo_scrip_resolver import build_sensex_weekly_symbol
from app.services.sensex_instrument_archive import (
    resolve_historical_sensex_option,
    upsert_instrument,
)


def test_resolve_from_archive_by_symbol(tmp_path, monkeypatch):
    from app.services import sensex_instrument_archive as mod

    db = tmp_path / "test.db"
    monkeypatch.setattr(mod, "_DB_PATH", db)

    exp = "2026-06-11"
    strike = 77100.0
    sym = build_sensex_weekly_symbol(strike, "CE", exp)
    upsert_instrument(
        exchange="BFO",
        trading_symbol=sym,
        instrument_token="12345678",
        expiry_date=exp,
        strike=strike,
        option_type="CE",
        source="test",
    )

    hit = resolve_historical_sensex_option(strike, "CE", expiry_date=exp, trade_date=exp)
    assert hit is not None
    assert hit.instrument_token == "12345678"
    assert hit.trading_symbol == sym


def test_resolve_missing_returns_none(tmp_path, monkeypatch):
    from app.services import sensex_instrument_archive as mod

    db = tmp_path / "test.db"
    monkeypatch.setattr(mod, "_DB_PATH", db)

    hit = resolve_historical_sensex_option(77100, "CE", expiry_date="2026-06-11", trade_date="2026-06-11")
    assert hit is None
