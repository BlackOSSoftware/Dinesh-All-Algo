"""TP2 trail applies only to remaining core (initial/re-entry) lots."""

from app.services.sensex_trend_core import (
    BarSlice,
    EngineState,
    EntryKind,
    OpenCycle,
    SignalKind,
    TrendParams,
    process_bar,
    tp1_level_for,
)


def _oc_call(ce: float, base: float, *, lots: int, core: int, avg: int, entries: int, **kw) -> OpenCycle:
    p = TrendParams()
    t1_avg = tp1_level_for("CALL", ce, p.tp1_pts)
    t1_core = tp1_level_for("CALL", ce, p.tp1_pts_initial)
    return OpenCycle(
        cycle_id=1,
        side="CALL",
        cycle_base=base,
        first_entry=ce,
        lots=lots,
        t1_level=t1_core,
        t1_level_avg=t1_avg,
        t1_level_core=t1_core,
        sl_level=ce - p.stop_distance,
        core_lots=core,
        avg_lots=avg,
        entries_filled=entries,
        entry_kind=EntryKind.INITIAL,
        **kw,
    )


def test_tp1_exits_avg_at_45_then_core_at_70():
    p = TrendParams()
    base = 76500.0
    ce = base + p.entry_trigger
    t1_avg = tp1_level_for("CALL", ce, p.tp1_pts)
    t1_core = tp1_level_for("CALL", ce, p.tp1_pts_initial)

    oc = _oc_call(ce, base, lots=5, core=2, avg=3, entries=4)
    state = EngineState(base_price=base, open_cycle=oc, initial_entry_consumed=True)

    prev = t1_avg - 1
    bar = BarSlice(high=t1_avg + 1, low=prev, close=t1_avg, prev_close=prev)
    state, signals = process_bar(state, p, bar)
    tp1_sigs = [s for s in signals if s.kind == SignalKind.PARTIAL_TP1]
    assert len(tp1_sigs) == 1
    assert tp1_sigs[0].exit_reason == "TP1_AVG"
    assert state.open_cycle.avg_lots == 0

    prev2 = t1_core - 1
    bar2 = BarSlice(high=t1_core + 1, low=prev2, close=t1_core, prev_close=prev2)
    state, signals2 = process_bar(state, p, bar2)
    tp1_sigs2 = [s for s in signals2 if s.kind == SignalKind.PARTIAL_TP1]
    assert any(s.exit_reason == "TP1" for s in tp1_sigs2)
    assert state.open_cycle.core_lots == 1
    assert state.open_cycle.lots == 1


def test_tp2_closes_only_remaining_core_lot():
    p = TrendParams()
    base = 76500.0
    ce = base + p.entry_trigger
    t1_core = tp1_level_for("CALL", ce, p.tp1_pts_initial)
    extreme = t1_core + 50

    oc = _oc_call(
        ce,
        base,
        lots=1,
        core=1,
        avg=0,
        entries=4,
        core_t1_done=True,
        avg_t1_done=True,
        trail_extreme=extreme,
    )
    state = EngineState(base_price=base, open_cycle=oc)

    trail_tp = extreme - p.tp2_trail
    prev = trail_tp + 5
    bar = BarSlice(high=prev, low=trail_tp - 1, close=trail_tp, prev_close=prev)
    state, signals = process_bar(state, p, bar)

    tp2 = [s for s in signals if s.kind == SignalKind.CLOSE_TP2]
    assert len(tp2) == 1
    assert tp2[0].close_lots == 1
    assert state.open_cycle is None


def test_initial_two_lots_core_tp1_at_70():
    p = TrendParams()
    base = 76500.0
    ce = base + p.entry_trigger
    t1_core = tp1_level_for("CALL", ce, p.tp1_pts_initial)

    oc = _oc_call(ce, base, lots=2, core=2, avg=0, entries=1)
    state = EngineState(base_price=base, open_cycle=oc, initial_entry_consumed=True)

    prev = t1_core - 1
    bar = BarSlice(high=t1_core + 1, low=prev, close=t1_core, prev_close=prev)
    state, signals = process_bar(state, p, bar)

    tp1_sigs = [s for s in signals if s.kind == SignalKind.PARTIAL_TP1]
    assert len(tp1_sigs) == 1
    assert tp1_sigs[0].exit_reason == "TP1"
    assert tp1_sigs[0].close_lots == 1
    assert state.open_cycle is not None
    assert state.open_cycle.core_lots == 1
