"""Dual TP1 (70 core / 45 avg) and SL trail rules."""

from app.services.sensex_trend_core import (
    BarSlice,
    EngineState,
    EntryKind,
    OpenCycle,
    SignalKind,
    TrendParams,
    open_cycle_sl_level,
    process_bar,
    tp1_level_for,
)


def test_initial_call_sl_is_first_entry_minus_stop():
    p = TrendParams()
    base = 77000.0
    first = base + p.entry_trigger  # 77191
    sl = open_cycle_sl_level("CALL", first, p, entry_kind=EntryKind.INITIAL, adaptive_ref=base)
    assert sl == 77000.0


def test_dual_tp1_levels():
    p = TrendParams(tp1_pts_initial=70.0, tp1_pts=45.0)
    first = 77191.0
    assert tp1_level_for("CALL", first, p.tp1_pts_initial) == 77261.0
    assert tp1_level_for("CALL", first, p.tp1_pts) == 77236.0


def test_avg_tp1_before_core_tp1():
    p = TrendParams(tp1_pts_initial=70.0, tp1_pts=45.0)
    base = 77000.0
    first = base + p.entry_trigger
    t1_avg = tp1_level_for("CALL", first, p.tp1_pts)
    t1_core = tp1_level_for("CALL", first, p.tp1_pts_initial)

    oc = OpenCycle(
        cycle_id=1,
        side="CALL",
        cycle_base=base,
        first_entry=first,
        lots=3,
        t1_level=t1_core,
        t1_level_avg=t1_avg,
        t1_level_core=t1_core,
        sl_level=first - p.stop_distance,
        core_lots=2,
        avg_lots=1,
        entries_filled=2,
        entry_kind=EntryKind.INITIAL,
    )
    state = EngineState(base_price=base, open_cycle=oc, initial_entry_consumed=True)

    prev = t1_avg - 1
    bar = BarSlice(high=t1_avg + 1, low=prev, close=t1_avg, prev_close=prev)
    state, signals = process_bar(state, p, bar)
    tp1 = [s for s in signals if s.kind == SignalKind.PARTIAL_TP1]
    assert len(tp1) == 1
    assert tp1[0].exit_reason == "TP1_AVG"
    assert state.open_cycle.avg_t1_done
    assert not state.open_cycle.core_t1_done


def test_sl_bumps_after_core_tp1():
    p = TrendParams(tp1_pts_initial=70.0, tp1_pts=45.0)
    base = 77000.0
    first = base + p.entry_trigger
    sl0 = first - p.stop_distance
    t1_core = tp1_level_for("CALL", first, p.tp1_pts_initial)

    oc = OpenCycle(
        cycle_id=1,
        side="CALL",
        cycle_base=base,
        first_entry=first,
        lots=2,
        t1_level=t1_core,
        t1_level_avg=tp1_level_for("CALL", first, p.tp1_pts),
        t1_level_core=t1_core,
        sl_level=sl0,
        avg_t1_done=True,
        core_lots=2,
        avg_lots=0,
        entries_filled=1,
        entry_kind=EntryKind.INITIAL,
    )
    state = EngineState(base_price=base, open_cycle=oc, initial_entry_consumed=True)

    prev = t1_core - 1
    bar = BarSlice(high=t1_core + 1, low=prev, close=t1_core, prev_close=prev)
    state, signals = process_bar(state, p, bar)
    assert any(s.exit_reason == "TP1" for s in signals if s.kind == SignalKind.PARTIAL_TP1)
    assert state.open_cycle.sl_level == sl0 + p.tp1_pts_initial
    tp1_sig = next(s for s in signals if s.kind == SignalKind.PARTIAL_TP1 and s.exit_reason == "TP1")
    assert tp1_sig.sl_level == sl0 + p.tp1_pts_initial
