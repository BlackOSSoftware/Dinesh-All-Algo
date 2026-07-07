"""Unit tests for Strategy 4 breakout logic."""

from app.services.breakout_logic import (
    compute_tp_sl,
    compute_triggers,
    simulate_day,
)


def _cfg(**overrides):
    base = {
        "startTime": "18:29",
        "endTime": "23:30",
        "market": "NATURAL_GAS",
        "lotSize": 4,
        "breakoutDistance": 0.5,
        "takeProfit": 1.0,
        "stopLoss": 0.8,
    }
    base.update(overrides)
    return base


def test_triggers_from_reference():
    buy, sell = compute_triggers(300.0, 0.5)
    assert buy == 300.5
    assert sell == 299.5


def test_tp_sl_buy():
    tp, sl = compute_tp_sl("BUY", 300.5, 1.0, 0.8)
    assert tp == 301.5
    assert sl == 299.7


def test_scenario_a_buy_tp():
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 299.8, "high": 300.1, "low": 299.5, "close": 300.0},
        {"time": "2024-06-01 18:30:00", "open": 300.0, "high": 301.6, "low": 300.4, "close": 301.4},
    ]
    rt, trades, _report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    assert rt["phase"] == "DONE"
    assert rt["realizedPnl"] == 4.0
    assert any(t["action"] == "INITIAL_BUY" for t in trades)
    assert any(t["action"] == "EXIT_TP" for t in trades)


def test_scenario_b_buy_sl_reverse_tp():
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 299.8, "high": 300.1, "low": 299.5, "close": 300.0},
        {"time": "2024-06-01 18:30:00", "open": 300.2, "high": 300.6, "low": 299.5, "close": 299.6},
        {"time": "2024-06-01 18:31:00", "open": 299.6, "high": 299.8, "low": 298.5, "close": 298.6},
    ]
    rt, trades, _report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    assert rt["phase"] == "DONE"
    assert any(t["action"] == "INITIAL_BUY" for t in trades)
    assert any(t["action"] == "EXIT_SL" for t in trades)
    assert any(t["action"] == "REVERSE_SELL" for t in trades)
    assert any(t["action"] == "EXIT_TP" for t in trades)
    assert rt["realizedPnl"] == 0.8  # (-0.8 + 1.0) * 4 lots


def test_sell_first_breakout():
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 300.2, "high": 300.3, "low": 299.8, "close": 300.0},
        {"time": "2024-06-01 18:30:00", "open": 300.0, "high": 300.1, "low": 299.4, "close": 299.5},
        {"time": "2024-06-01 18:31:00", "open": 299.5, "high": 299.6, "low": 298.4, "close": 298.5},
    ]
    rt, trades, _report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    assert any(t["action"] == "INITIAL_SELL" for t in trades)
    assert rt["phase"] == "DONE"


def test_daily_report_fields():
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 299.8, "high": 300.1, "low": 299.5, "close": 300.0},
        {"time": "2024-06-01 18:30:00", "open": 300.0, "high": 301.6, "low": 300.4, "close": 301.4},
    ]
    _rt, _trades, report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    assert report["referenceClose"] == 300.0
    assert report["buyTrigger"] == 300.5
    assert report["sellTrigger"] == 299.5
    assert report["initialDirection"] == "BUY"
    assert report["result"] == "TP"
    assert len(report["roundTrips"]) == 1
    assert report["roundTrips"][0]["tradePnl"] == 4.0


def test_never_both_initial_directions():
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 300.0, "high": 300.2, "low": 299.8, "close": 300.0},
        {"time": "2024-06-01 18:30:00", "open": 300.0, "high": 301.6, "low": 299.4, "close": 301.0},
    ]
    _rt, events, report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    initials = [e for e in events if str(e.get("action", "")).startswith("INITIAL_")]
    assert len(initials) <= 1
    assert report["initialDirection"] in ("BUY", "SELL", None)

def test_reverse_not_exits_same_candle():
    """Reverse entry must not exit on the same 1-min bar (policy)."""
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 313.1, "high": 313.4, "low": 313.0, "close": 313.3},
        {"time": "2024-06-01 18:30:00", "open": 313.4, "high": 314.0, "low": 313.7, "close": 313.8},
        {"time": "2024-06-01 18:32:00", "open": 313.9, "high": 314.0, "low": 312.9, "close": 313.0},
        {"time": "2024-06-01 18:33:00", "open": 313.0, "high": 313.1, "low": 311.9, "close": 312.0},
    ]
    _rt, events, report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    reverse_entries = [e for e in events if e.get("action") == "REVERSE_SELL"]
    reverse_exits = [e for e in events if str(e.get("action", "")).startswith("EXIT_") and e.get("entryType") == "Reverse"]
    assert len(reverse_entries) == 1
    assert not reverse_exits or reverse_exits[0]["time"] != reverse_entries[0]["time"]
    assert "Reverse" in (report.get("result") or "")


def test_no_breakout_no_trade():
    candles = [
        {"time": "2024-06-01 18:29:00", "open": 300.0, "high": 300.2, "low": 299.8, "close": 300.0},
        {"time": "2024-06-01 18:30:00", "open": 300.0, "high": 300.2, "low": 299.8, "close": 300.0},
    ]
    rt, trades, report = simulate_day(candles, _cfg(), session_date="2024-06-01")
    assert rt["phase"] == "NO_TRADE"
    assert trades == []
    assert report["result"] == "No breakout"

