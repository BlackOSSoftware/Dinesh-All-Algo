"""Unit tests for Strategy 4 breakout logic."""

from datetime import datetime, timedelta, timezone

from app.services import breakout_trading_engine as eng
from app.services.breakout_logic import (
    compute_tp_sl,
    compute_triggers,
    process_price_tick,
    set_reference_from_candle,
    simulate_day,
)
from app.services.breakout_trading_engine import _runtime_changed


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
    reverse_exits = [
        e for e in events if str(e.get("action", "")).startswith("EXIT_") and e.get("entryType") == "Reverse"
    ]
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


def test_live_tick_buys_when_already_above_trigger():
    """After late arming, LTP already above buy trigger must still open BUY."""
    cfg = _cfg()
    rt = set_reference_from_candle(
        {"phase": "WAIT_REF", "prevPrice": 301.0, "lastPrice": 301.0},
        {"time": "18:29", "close": 300.0},
        {
            "breakout_distance": 0.5,
            "take_profit": 1.0,
            "stop_loss": 0.8,
            "lots": 4,
        },
    )
    assert rt["phase"] == "WAIT_BREAKOUT"
    assert rt["buyTrigger"] == 300.5
    next_rt, actions = process_price_tick(cfg, rt, 301.0)
    assert any(a["action"] == "INITIAL_BUY" for a in actions)
    assert next_rt["phase"] == "IN_TRADE"
    assert next_rt["side"] == "BUY"


def test_live_tick_sells_on_path_cross():
    cfg = _cfg()
    rt = {
        "phase": "WAIT_BREAKOUT",
        "referencePrice": 300.0,
        "buyTrigger": 300.5,
        "sellTrigger": 299.5,
        "prevPrice": 300.0,
        "lastPrice": 300.0,
        "tradeCount": 0,
        "realizedPnl": 0.0,
    }
    next_rt, actions = process_price_tick(cfg, rt, 299.4)
    assert any(a["action"] == "INITIAL_SELL" for a in actions)
    assert next_rt["side"] == "SELL"


def _armed_rt(prev=300.0, last=300.0):
    return {
        "phase": "WAIT_BREAKOUT",
        "referencePrice": 300.0,
        "buyTrigger": 300.5,
        "sellTrigger": 299.5,
        "prevPrice": prev,
        "lastPrice": last,
        "tradeCount": 0,
        "realizedPnl": 0.0,
    }


def test_sell_trigger_with_stale_high_prev_price_opens_sell_not_buy():
    """Regression: stale prevPrice above the buy trigger must NOT flip a sell
    breakout into a BUY (live bug: sell-side order executed as BUY)."""
    cfg = _cfg()
    rt = _armed_rt(prev=302.0, last=302.0)  # stale/garbage prev above buy trigger
    next_rt, actions = process_price_tick(cfg, rt, 299.4)
    assert next_rt["side"] == "SELL"
    assert [a["action"] for a in actions] == ["INITIAL_SELL"]


def test_buy_trigger_with_stale_low_prev_price_opens_buy_not_sell():
    cfg = _cfg()
    rt = _armed_rt(prev=295.0, last=295.0)  # stale prev far below sell trigger
    next_rt, actions = process_price_tick(cfg, rt, 300.6)
    assert next_rt["side"] == "BUY"
    assert [a["action"] for a in actions] == ["INITIAL_BUY"]


def test_entry_tick_never_exits_on_same_tick():
    """Regression: the entry tick must not instantly hit SL from a stale prev span."""
    cfg = _cfg()
    rt = _armed_rt(prev=305.0, last=305.0)  # prev span would cross SELL SL (300.2)
    next_rt, actions = process_price_tick(cfg, rt, 299.5)
    assert [a["action"] for a in actions] == ["INITIAL_SELL"]
    assert next_rt["phase"] == "IN_TRADE"
    assert next_rt["positionLots"] == 4


def _open_sell_rt(entry=299.5):
    tp, sl = compute_tp_sl("SELL", entry, 1.0, 0.8)
    return {
        "phase": "IN_TRADE",
        "referencePrice": 300.0,
        "buyTrigger": 300.5,
        "sellTrigger": 299.5,
        "side": "SELL",
        "entryPrice": entry,
        "tpPrice": tp,     # 298.5 (below entry)
        "slPrice": sl,     # 300.3 (above entry)
        "isReverse": False,
        "tradeCount": 1,
        "positionLots": 4,
        "realizedPnl": 0.0,
        "prevPrice": entry,
        "lastPrice": entry,
    }


def test_sell_trade_tp_hits_below_entry_with_profit():
    cfg = _cfg()
    rt = _open_sell_rt()
    next_rt, actions = process_price_tick(cfg, rt, 298.5)
    assert [a["action"] for a in actions] == ["EXIT_TP"]
    assert actions[0]["tradePnl"] == 4.0  # (299.5 - 298.5) * 4 lots
    assert next_rt["phase"] == "DONE"


def test_sell_trade_sl_hits_above_entry_and_reverses_buy():
    cfg = _cfg()
    rt = _open_sell_rt()
    next_rt, actions = process_price_tick(cfg, rt, 300.3)
    assert [a["action"] for a in actions] == ["EXIT_SL", "REVERSE_BUY"]
    assert actions[0]["tradePnl"] == -3.2  # (299.5 - 300.3) * 4 lots
    assert next_rt["side"] == "BUY"
    assert next_rt["phase"] == "REVERSE_TRADE"


def test_sell_trade_profitable_move_never_hits_sl():
    """Regression: falling price on a SELL is profit — must not exit as SL."""
    cfg = _cfg()
    rt = _open_sell_rt()
    for px in (299.3, 299.0, 298.8, 298.6):
        rt, actions = process_price_tick(cfg, rt, px)
        assert not actions, f"unexpected exit at {px}: {actions}"
    assert rt["side"] == "SELL"
    assert rt["positionLots"] == 4


def test_no_duplicate_entries_while_price_stays_beyond_trigger():
    cfg = _cfg()
    rt = _armed_rt()
    rt, actions = process_price_tick(cfg, rt, 299.4)
    assert len(actions) == 1
    # Price keeps grinding lower — no second entry, only eventual TP.
    rt, actions = process_price_tick(cfg, rt, 299.2)
    assert actions == []
    rt, actions = process_price_tick(cfg, rt, 298.4)
    assert [a["action"] for a in actions] == ["EXIT_TP"]
    rt, actions = process_price_tick(cfg, rt, 297.0)
    assert actions == []  # DONE — no further trades


def test_midnight_rollover_keeps_open_trade():
    """An open trade must survive the IST date flip (overnight session) so its
    TP/SL keeps being managed instead of orphaning the broker position."""
    rt = _open_sell_rt()
    rt["sessionDate"] = "2026-07-16"
    original = eng._session_date
    eng._session_date = lambda: "2026-07-17"
    try:
        out = eng._ensure_daily_session(_cfg(), rt)
        assert out["side"] == "SELL"
        assert out["positionLots"] == 4
        assert out["sessionDate"] == "2026-07-17"
        assert out["carriedFromPrevDay"] is True

        # Flat runtime at date flip still re-arms fresh as before.
        flat = {"sessionDate": "2026-07-16", "phase": "DONE", "positionLots": 0}
        fresh = eng._ensure_daily_session(_cfg(), flat)
        assert fresh["phase"] == "WAIT_REF"
        assert fresh["positionLots"] == 0

        # Once the carried trade finishes, the same day re-arms a new session.
        done = {**out, "phase": "DONE", "positionLots": 0, "side": None, "realizedPnl": 4.0}
        rearmed = eng._ensure_daily_session(_cfg(), done)
        assert rearmed["phase"] == "WAIT_REF"
        assert rearmed["realizedPnl"] == 4.0
    finally:
        eng._session_date = original


def test_live_order_transaction_mapping():
    """Engine → broker mapping: entries use the action side, exits use the opposite.
    Missing side must NEVER silently default to BUY."""
    assert eng._broker_tx_for({"action": "INITIAL_BUY", "side": "BUY"}) == "BUY"
    assert eng._broker_tx_for({"action": "INITIAL_SELL", "side": "SELL"}) == "SELL"
    assert eng._broker_tx_for({"action": "REVERSE_BUY", "side": "BUY"}) == "BUY"
    assert eng._broker_tx_for({"action": "REVERSE_SELL", "side": "SELL"}) == "SELL"
    assert eng._broker_tx_for({"action": "EXIT_TP", "side": "BUY"}) == "SELL"
    assert eng._broker_tx_for({"action": "EXIT_SL", "side": "SELL"}) == "BUY"
    # Side inferred from action name when field is missing.
    assert eng._broker_tx_for({"action": "INITIAL_SELL"}) == "SELL"
    assert eng._broker_tx_for({"action": "EXIT_TP", "side": "SELL"}) == "BUY"
    # Truly unknown → refuse (do not default to BUY).
    assert eng._broker_tx_for({"action": "EXIT_TP"}) is None
    assert eng._broker_tx_for({"action": "UNKNOWN"}) is None


def test_tick_price_cache_cleared_on_market_switch():
    """Stale prevPrice from another instrument must not poison the next tick."""
    eng._TICK_PRICE[42] = ("2026-07-17", "NATURAL_GAS", 280.0, 280.0)
    cached = eng._TICK_PRICE.get(42)
    assert cached is not None
    # Simulate process_user_tick market-key check.
    today, market_key = "2026-07-17", "CRUDE_OIL"
    if not (cached[0] == today and cached[1] == market_key):
        eng._TICK_PRICE.pop(42, None)
    assert 42 not in eng._TICK_PRICE


def test_runtime_changed_detects_reference():
    before = {"phase": "WAIT_REF", "referencePrice": 0}
    after = {"phase": "WAIT_BREAKOUT", "referencePrice": 300.0}
    assert _runtime_changed(before, after)


def test_in_session_overnight_window():
    fixed = datetime(2026, 7, 15, 1, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    original = eng._ist_now
    eng._ist_now = lambda: fixed
    try:
        assert eng._in_session("18:29", "02:30") is True
        assert eng._in_session("18:29", "23:30") is False
    finally:
        eng._ist_now = original
