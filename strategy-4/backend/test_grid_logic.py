"""Grid per-level state machine tests."""

from app.services.grid_backtest_candles import process_backtest_candle
from app.services.grid_logic import bootstrap_initial_entry, default_runtime, fresh_grid_runtime, process_price_tick, seed_runtime_market_price


def _cfg(ref=300):
    return {
        "startTime": "09:15",
        "endTime": "23:30",
        "market": "CRUDE_OIL",
        "referencePrice": float(ref),
        "initialLots": 10,
        "gridGap": 2,
        "gridLevelsAbove": 3,
        "gridLevelsBelow": 3,
        "lotsPerGrid": 2,
    }


def _run_path(path: list[float], ref=300):
    cfg = _cfg(ref)
    rt = default_runtime()
    rt, boot = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=ref)
    actions = list(boot)
    for px in path:
        rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, px)
        actions.extend(acts)
    return rt, actions


def test_no_u1_ping_pong_after_reenter():
    rt, actions = _run_path([298.0, 300.5, 299.9, 300.5], ref=298)
    u1 = [a for a in actions if a["level"] == "U1"]
    exits = [a for a in u1 if a["action"] == "EXIT"]
    reenters = [a for a in u1 if a["action"] == "REENTER"]
    assert len(exits) <= len(reenters) + 1


def test_u_ladder_up_then_down():
    rt, actions = _run_path([300.0, 302.0, 304.0, 306.0, 304.0, 302.0, 300.0])
    pairs = [(a["action"], a["level"]) for a in actions]
    assert pairs == [
        ("INITIAL_BUY", "BASE"),
        ("EXIT", "U1"),
        ("EXIT", "U2"),
        ("EXIT", "U3"),
        ("REENTER", "U2"),
        ("REENTER", "U1"),
        ("REENTER", "BASE"),
    ]
    assert rt["positionLots"] == 10


def test_no_second_u1_exit_without_u2():
    rt, actions = _run_path([300.0, 302.0, 300.0, 302.0])
    pairs = [(a["action"], a["level"]) for a in actions]
    assert pairs.count(("EXIT", "U1")) == 1


def test_d_add_exit_at_base_not_d():
    rt, actions = _run_path([300.0, 298.0, 300.0])
    pairs = [(a["action"], a["level"]) for a in actions]
    assert pairs == [
        ("INITIAL_BUY", "BASE"),
        ("ADD", "D1"),
        ("EXIT", "BASE"),
    ]
    assert rt["positionLots"] == 10


def test_d_unwind_at_base_when_position_equals_core():
    """D1 add unwinds at BASE up-cross; not batched with deeper D levels."""
    cfg = _cfg(300)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 298.0)
    assert rt["positionLots"] == 12
    assert rt["levelStates"].get("D1") == "added"
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 300.0)
    assert any(a["action"] == "EXIT" and a["level"] == "BASE" and a.get("unwindD") == "D1" for a in acts)
    assert rt["positionLots"] == 10
    assert rt["levelStates"].get("D1") == "neutral"


def test_d_unwind_at_base_before_upper_in_candle():
    cfg = _cfg(300)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 298.0)
    rt, acts = process_backtest_candle(
        cfg, rt, open_price=298.5, close_price=303.0, high_price=304.0, low_price=298.5
    )
    pairs = [(a["action"], a["level"]) for a in acts]
    base_idx = next(i for i, p in enumerate(pairs) if p == ("EXIT", "BASE"))
    u2_idx = next((i for i, p in enumerate(pairs) if p == ("EXIT", "U2")), len(pairs))
    assert base_idx < u2_idx


def test_u2_exit_after_base_unwind_when_u1_still_sold():
    """After U1 sold + D1 add + BASE unwind, next up exit can include U1 then U2."""
    cfg = _cfg(300)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 302.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 298.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 300.0)
    rt, acts = process_backtest_candle(
        cfg, rt, open_price=300.5, close_price=303.5, high_price=304.3, low_price=300.5
    )
    pairs = [(a["action"], a["level"]) for a in acts]
    assert ("EXIT", "U2") in pairs
    u1_exits = [a for a in acts if a["action"] == "EXIT" and a["level"] == "U1"]
    assert len(u1_exits) == 1


def test_inventory_floor_after_full_upper_ladder():
    rt, actions = _run_path([302.0, 304.0, 306.0])
    assert rt["positionLots"] == 4
    assert rt["inventoryFloorLots"] == 4
    assert not any(a["action"] == "EXIT" and a["positionAfter"] == 0 for a in actions)


def test_no_position_below_floor_after_base_unwind_reset_cycle():
    """BASE unwind resets U states; re-upper exits must not push below floor."""
    cfg = _cfg(300)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 302.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 304.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 306.0)
    assert rt["positionLots"] == 4
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 298.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 300.5)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 302.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 304.0)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 306.0)
    assert rt["positionLots"] >= 4
    assert rt["positionLots"] > 0


def test_two_d_unwinds_on_single_300_cross():
    cfg = _cfg(300)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, _ = process_price_tick({**cfg, "grid_runtime": rt}, rt, 296.0)
    assert rt["levelStates"].get("D1") == "added"
    assert rt["levelStates"].get("D2") == "added"
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 300.5)
    pairs = [(a["action"], a["level"], a.get("unwindD")) for a in acts if a["action"] == "EXIT"]
    assert pairs == [("EXIT", "D1", "D2"), ("EXIT", "BASE", "D1")]
    assert rt["positionLots"] == 10


def test_d_two_adds_two_base_exits():
    rt, actions = _run_path([300.0, 296.0, 300.5, 298.0, 300.5])
    pairs = [(a["action"], a["level"]) for a in actions]
    assert ("ADD", "D1") in pairs
    assert ("ADD", "D2") in pairs
    assert pairs.count(("EXIT", "D1")) == 1
    assert pairs.count(("EXIT", "BASE")) == 2
    assert rt["positionLots"] == 10


def test_grid_fill_always_level_price_not_ltp():
    """Paper/live accounting uses grid level (306), never raw LTP (308.90)."""
    from app.services.grid_logic import grid_order_price

    cfg = _cfg(306)
    rt = fresh_grid_runtime(306.0)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 305.98)
    assert len(acts) == 1
    assert acts[0]["fillPrice"] == 306.0
    assert acts[0]["levelPrice"] == 306.0
    assert grid_order_price(acts[0]["levelPrice"]) == 306.0
    assert rt["avgEntryPrice"] == 306.0
    from app.services.grid_logic import ltp_matches_grid_level

    assert ltp_matches_grid_level(306.0, 306.0, 2.0)
    assert ltp_matches_grid_level(306.08, 306.0, 2.0)
    assert not ltp_matches_grid_level(308.90, 306.0, 2.0)
    assert not ltp_matches_grid_level(306.30, 306.0, 2.0)


def test_no_entry_when_started_above_base_without_touching():
    """LTP above BASE at algo start must not buy until price pulls back to BASE."""
    cfg = _cfg(306)
    rt = fresh_grid_runtime(306.30)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 306.30)
    assert acts == []
    assert rt["positionLots"] == 0
    assert not rt["baseEntered"]

    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 305.95)
    assert len(acts) == 1
    assert acts[0]["action"] == "INITIAL_BUY"
    assert acts[0]["fillPrice"] == 306.0


def test_no_entry_until_base_crossed():
    """Price above BASE at algo start — no buy until price actually crosses reference."""
    cfg = _cfg(310)
    rt = fresh_grid_runtime(311.0)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 311.0)
    assert acts == []
    assert rt["positionLots"] == 0
    assert not rt["baseEntered"]

    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 309.5)
    assert len(acts) == 1
    assert acts[0]["action"] == "INITIAL_BUY"
    assert acts[0]["level"] == "BASE"
    assert acts[0]["fillPrice"] == 310.0
    assert rt["positionLots"] == 10
    assert rt["avgEntryPrice"] == 310.0


def test_no_entry_on_up_cross_when_started_above_base():
    cfg = _cfg(310)
    rt = fresh_grid_runtime(313.0)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 312.0)
    assert acts == []
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 311.0)
    assert not any(a["action"] == "INITIAL_BUY" for a in acts)
    assert rt["positionLots"] == 0


def test_entry_on_up_cross_when_started_below_base():
    cfg = _cfg(310)
    rt = fresh_grid_runtime(305.0)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 305.0)
    assert acts == []
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 311.0)
    assert len(acts) == 1
    assert acts[0]["action"] == "INITIAL_BUY"


def test_touch_entry_when_price_sits_at_base():
    """LTP at BASE without tick-to-tick cross (3s poll) still triggers entry."""
    cfg = _cfg(310.4)
    rt = fresh_grid_runtime(310.4)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 310.4)
    assert len(acts) == 1
    assert acts[0]["action"] == "INITIAL_BUY"
    assert acts[0]["fillPrice"] == 310.4
    assert rt["positionLots"] == 10


def test_touch_entry_after_price_reaches_base():
    cfg = _cfg(310.4)
    rt = fresh_grid_runtime(313.0)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 312.0)
    assert acts == []
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 310.4)
    assert len(acts) == 1
    assert acts[0]["action"] == "INITIAL_BUY"


def test_bootstrap_starts_at_reference():
    cfg = _cfg(300)
    rt = default_runtime()
    rt, acts = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    assert len(acts) == 1
    assert acts[0]["action"] == "INITIAL_BUY"
    assert acts[0]["level"] == "BASE"
    assert acts[0]["levelPrice"] == 300.0
    assert rt["positionLots"] == 10


def test_ref_300_u1_at_302_not_298():
    cfg = _cfg(300)
    rt = default_runtime()
    rt, boot = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, acts = process_price_tick({**cfg, "grid_runtime": rt}, rt, 302.0)
    pairs = [(a["action"], a["level"], a["levelPrice"]) for a in boot + acts]
    assert pairs[0] == ("INITIAL_BUY", "BASE", 300.0)
    assert ("EXIT", "U1", 302.0) in pairs
    assert not any(a["levelPrice"] == 298.0 and a["action"] == "INITIAL_BUY" for a in boot + acts)


def test_no_u1_reenter_after_single_u1_exit():
    rt, actions = _run_path([302.0, 301.9])
    assert ("EXIT", "U1") in [(a["action"], a["level"]) for a in actions]
    assert not any(a["action"] == "REENTER" and a["level"] == "U1" for a in actions)


def test_u1_reenter_after_u2_exit_on_way_down():
    rt, actions = _run_path([302.0, 304.0, 300.0])
    pairs = [(a["action"], a["level"]) for a in actions]
    assert ("EXIT", "U1") in pairs
    assert ("EXIT", "U2") in pairs
    assert ("REENTER", "U1") in pairs
    assert ("REENTER", "BASE") in pairs


def test_no_u3_reenter_exit_churn():
    rt, actions = _run_path([302.0, 304.0, 306.0, 305.9, 306.0])
    u3 = [a for a in actions if a["level"] == "U3"]
    exits = [a for a in u3 if a["action"] == "EXIT"]
    reenters = [a for a in u3 if a["action"] == "REENTER"]
    assert len(exits) <= len(reenters) + 1


def test_candle_high_captures_u1_before_u2():
    cfg = _cfg(300)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=300)
    rt, acts = process_backtest_candle(
        cfg, rt, open_price=300.0, close_price=301.0, high_price=304.0, low_price=300.0
    )
    levels = [(a["action"], a["level"]) for a in acts]
    assert ("EXIT", "U1") in levels
    assert ("EXIT", "U2") in levels


def test_d_unwind_sequential_adjacent_levels():
    """D2 unwinds at D1 cross; D1 unwinds at BASE — never both at BASE."""
    rt, actions = _run_path([290.7, 288.7, 286.7, 288.7, 290.7], ref=290.7)
    pairs = [(a["action"], a["level"], a.get("unwindD")) for a in actions]
    assert pairs[0] == ("INITIAL_BUY", "BASE", None)
    assert ("ADD", "D1", None) in pairs
    assert ("ADD", "D2", None) in pairs
    assert ("EXIT", "D1", "D2") in pairs
    assert ("EXIT", "BASE", "D1") in pairs
    assert not any(a["action"] == "EXIT" and a["level"] == "BASE" and a.get("unwindD") == "D2" for a in actions)
    assert rt["positionLots"] == 10


def test_validate_grid_sequence_catches_skipped_u1():
    from app.services.grid_logic import validate_grid_trade_sequence

    bad = [
        {"action": "INITIAL_BUY", "level": "BASE"},
        {"action": "REENTER", "level": "BASE"},
        {"action": "EXIT", "level": "U2", "unwindD": None},
    ]
    errors = validate_grid_trade_sequence(bad, max_upper=3, max_lower=3)
    assert any("EXIT U2 missing prior EXIT U1" in e for e in errors)


def test_backtest_candle_blocks_u1_churn():
    cfg = _cfg(298)
    rt = default_runtime()
    rt, _ = bootstrap_initial_entry({**cfg, "grid_runtime": rt}, rt, fill_price=298)
    rt, _ = process_backtest_candle(cfg, rt, open_price=298.0, close_price=298.0, skip_open_segment=True)
    rt, a1 = process_backtest_candle(cfg, rt, open_price=300.2, close_price=300.5)
    rt, a2 = process_backtest_candle(cfg, rt, open_price=300.4, close_price=299.9)
    rt, a3 = process_backtest_candle(cfg, rt, open_price=300.1, close_price=300.2)
    u1_all = [a for a in a1 + a2 + a3 if a["level"] == "U1"]
    assert len([a for a in u1_all if a["action"] == "EXIT"]) <= 1
