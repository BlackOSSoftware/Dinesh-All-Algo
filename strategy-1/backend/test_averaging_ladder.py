"""CALL averaging ladder: 2 lots initial, then 1 lot every 45pt down (max 4 entries)."""

from app.services.sensex_trend_core import (
    BarSlice,
    EngineState,
    EntryKind,
    OpenCycle,
    SignalKind,
    TrendParams,
    cycle_sl,
    next_add_level,
    process_bar,
    resolve_signal_strike,
)


def test_call_averaging_levels_every_45_from_first_entry():
    p = TrendParams(averaging_gap=45.0, max_entries=4, initial_lots=2, add_lots=1)
    base = 76587.0
    first = base + p.entry_trigger  # 76778

    assert next_add_level("CALL", first, 1, p) == first - 45
    assert next_add_level("CALL", first, 2, p) == first - 90
    assert next_add_level("CALL", first, 3, p) == first - 135


def test_averaging_strike_uses_nearest_at_that_index_level():
    # 76733 → 76700 CE, 76643 → 76600 CE
    assert resolve_signal_strike(
        side="CALL", index_price=76733, entry_kind=EntryKind.AVERAGE, strike_offset=200
    ) == 76700
    assert resolve_signal_strike(
        side="CALL", index_price=76643, entry_kind=EntryKind.AVERAGE, strike_offset=200
    ) == 76600


def test_three_averaging_adds_after_initial_two_lots():
    p = TrendParams()
    base = 76587.0
    first = base + p.entry_trigger
    sl = first - p.stop_distance

    oc = OpenCycle(
        cycle_id=1,
        side="CALL",
        cycle_base=base,
        first_entry=first,
        lots=2,
        t1_level=first + p.tp1_pts_initial,
        t1_level_avg=first + p.tp1_pts,
        t1_level_core=first + p.tp1_pts_initial,
        sl_level=sl,
        entries_filled=1,
        core_lots=2,
        avg_lots=0,
        entry_kind=EntryKind.INITIAL,
        option_strike=77000,
    )
    state = EngineState(base_price=base, open_cycle=oc, initial_entry_consumed=True)

    for step in (1, 2, 3):
        level = first - p.averaging_gap * step
        assert level > sl
        prev = level + 10
        bar = BarSlice(high=prev, low=level - 1, close=level, prev_close=prev)
        state, signals = process_bar(state, p, bar)
        add = [s for s in signals if s.kind == SignalKind.OPEN_AVERAGE]
        assert len(add) == 1
        assert add[0].lots == 1
        assert add[0].price == level

    assert state.open_cycle is not None
    assert state.open_cycle.entries_filled == 4
    assert state.open_cycle.lots == 5
    assert state.open_cycle.core_lots == 2
    assert state.open_cycle.avg_lots == 3


def test_all_call_averaging_levels_stay_above_cycle_sl():
    p = TrendParams()
    base = 76587.0
    first = base + p.entry_trigger
    sl = first - p.stop_distance

    for i in range(1, p.max_entries):
        level = next_add_level("CALL", first, i, p)
        assert level > sl, f"Averaging level #{i + 1} must stay above SL ({sl})"
