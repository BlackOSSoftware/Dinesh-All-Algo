"""Tests for auto-detected SENSEX expiry calendar."""

from datetime import datetime

from app.services import sensex_expiry as se


def test_parse_expiry_from_symbol():
    dt = se._expiry_from_symbol("SENSEX17JUN2582000CE")
    assert dt is not None
    assert dt.month == 6


def test_expiry_for_week_uses_calendar(monkeypatch):
    def fake_calendar():
        dates = ["2026-06-17"]
        week_map = {(2026, 25): "2026-06-17"}
        return dates, week_map, "test"

    monkeypatch.setattr(se, "_expiry_calendar", fake_calendar)
    assert se.contract_expiry_for_week("2026-06-17") == "2026-06-17"
    assert se.expiry_for_week("2026-06-17") == "2026-06-17"
    assert se.is_sensex_expiry_date("2026-06-17") is True
    assert se.is_sensex_expiry_date("2026-06-18") is False


def test_may_2026_bakri_id_session_preponed_to_wednesday():
    """28 May 2026 was Bakri Id — weekly expiry session traded on 27 May."""
    assert se.expiry_for_week("2026-05-27") == "2026-05-27"
    assert se.contract_expiry_for_week("2026-05-27") == "2026-05-28"
    assert se.is_sensex_expiry_date("2026-05-27") is True
    assert se.is_sensex_expiry_date("2026-05-28") is False


def test_is_expiry_session_day_respects_flag():
    from app.services.breakout_logic import is_expiry_session_day

    assert is_expiry_session_day("2026-06-18", {"expiryDayOnly": False}) is True
