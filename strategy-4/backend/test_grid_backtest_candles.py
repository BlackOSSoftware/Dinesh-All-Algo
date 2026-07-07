"""Backtest OHLC candle execution tests."""

from app.services.grid_backtest_candles import process_backtest_candle
from app.services.grid_logic import bootstrap_initial_entry, default_runtime


def _cfg(ref=300):
    return {
        "startTime": "09:15",
        "endTime": "23:30",
        "market": "CRUDE_OIL",
        "referencePrice": ref,
        "initialLots": 10,
        "gridGap": 2,
        "gridLevelsAbove": 3,
        "gridLevelsBelow": 3,
        "lotsPerGrid": 2,
    }


def test_one_action_per_level_per_candle():
    cfg = _cfg()
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, acts1 = process_backtest_candle(cfg, rt, open_price=300.6, close_price=300.5)
    u1 = [a for a in acts1 if a["level"] == "U1"]
    assert len(u1) <= 1, u1


def test_candle_gap_visits_u1_before_u2():
    """After BASE reenter, a jump toward U2 must process U1 (292.70) before U2 (294.70)."""
    cfg = _cfg(290.7)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=290.7)
    rt, _ = process_backtest_candle(cfg, rt, open_price=290.7, close_price=290.7, skip_open_segment=True)
    rt["levelStates"] = {"U1": "sold"}
    rt["positionLots"] = 8
    rt["upperReenterHold"] = {"U1": False}
    rt, re_acts = process_backtest_candle(cfg, rt, open_price=290.7, close_price=289.5, low_price=289.5)
    assert any(a["action"] == "REENTER" and a["level"] == "BASE" for a in re_acts)
    assert rt["levelStates"].get("U1") == "neutral"
    rt, exit_acts = process_backtest_candle(
        cfg,
        rt,
        open_price=291.0,
        close_price=294.5,
        high_price=294.7,
        low_price=291.0,
    )
    exits = [(a["level"], a["fillPrice"]) for a in exit_acts if a["action"] == "EXIT"]
    assert ("U1", 292.7) in exits
    assert ("U2", 294.7) in exits
    assert exits.index(("U1", 292.7)) < exits.index(("U2", 294.7))


def test_waypoint_u1_blocked_then_u2_only_bug():
    """REENTER @ BASE then 291->292.7->294.7 path must EXIT U1 before U2."""
    from app.services.grid_logic import process_price_tick, validate_grid_trade_sequence

    cfg = _cfg(290.7)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=290.7)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 292.7)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 290.7)
    assert rt["upperArmLocks"].get("U1") is True
    rt, acts = process_backtest_candle(
        cfg,
        rt,
        open_price=291.0,
        close_price=294.5,
        high_price=294.7,
        low_price=291.0,
    )
    exits = [a for a in acts if a["action"] == "EXIT"]
    assert len(exits) == 2
    assert exits[0]["level"] == "U1"
    assert exits[0]["fillPrice"] == 292.7
    assert exits[1]["level"] == "U2"
    assert exits[1]["fillPrice"] == 294.7
    assert validate_grid_trade_sequence(acts, max_upper=3, max_lower=3) == []
