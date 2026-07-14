"""
Pure SENSEX Adaptive Trend Averaging engine — shared by live trading and backtest.

No DB, no broker calls. Deterministic bar/tick processing without look-ahead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, field
from enum import Enum
from typing import Any


class SignalKind(str, Enum):
    OPEN_INITIAL = "OPEN_INITIAL"
    OPEN_AVERAGE = "OPEN_AVERAGE"
    PARTIAL_TP1 = "PARTIAL_TP1"
    CLOSE_TP2 = "CLOSE_TP2"
    CLOSE_SL = "CLOSE_SL"
    CLOSE_SESSION = "CLOSE_SESSION"
    SET_WAIT_REENTRY = "SET_WAIT_REENTRY"


class EntryKind(str, Enum):
    INITIAL = "INITIAL"
    AVERAGE = "AVERAGE"
    REENTRY = "REENTRY"


@dataclass
class TrendParams:
    entry_trigger: float = 191.0
    strike_offset: float = 200.0
    initial_lots: int = 2
    add_lots: int = 1
    averaging_gap: float = 45.0
    max_entries: int = 4
    tp1_pts: float = 45.0
    tp1_pts_initial: float = 70.0
    tp2_trail: float = 30.0
    stop_distance: float = 191.0
    re_entry_enabled: bool = True
    re_entry_gap: float = 70.0
    max_re_entries: int | None = 3
    call_enabled: bool = True
    put_enabled: bool = True
    first_entry_enabled: bool = True
    max_trades_per_day: int | None = None
    daily_max_loss: float | None = None
    entry_lots: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.entry_lots = normalize_entry_lots(
            self.entry_lots or None,
            max_entries=self.max_entries,
            initial_lots=self.initial_lots,
            add_lots=self.add_lots,
        )
        self.initial_lots = self.entry_lots[0]
        if len(self.entry_lots) > 1:
            self.add_lots = self.entry_lots[1]

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> TrendParams:
        def _f(*keys: str, default: float) -> float:
            for k in keys:
                v = cfg.get(k)
                if v is None or v == "":
                    continue
                try:
                    x = float(v)
                    if x > 0:
                        return x
                except (TypeError, ValueError):
                    continue
            return default

        def _i(*keys: str, default: int) -> int:
            for k in keys:
                v = cfg.get(k)
                if v is None or v == "":
                    continue
                try:
                    x = int(float(v))
                    if x > 0:
                        return x
                except (TypeError, ValueError):
                    continue
            return default

        direction = str(cfg.get("tradeDirection") or "BOTH").upper()
        call_on = bool(cfg.get("callEnabled", True))
        put_on = bool(cfg.get("putEnabled", True))
        if direction == "CALL_ONLY":
            call_on, put_on = True, False
        elif direction == "PUT_ONLY":
            call_on, put_on = False, True

        max_re = cfg.get("maxReEntries")
        max_re_i: int | None
        try:
            max_re_i = int(float(max_re)) if max_re is not None and str(max_re).strip() != "" else 3
            if max_re_i <= 0:
                max_re_i = None
        except (TypeError, ValueError):
            max_re_i = 3

        max_trades = cfg.get("maxTradesPerDay")
        max_trades_i: int | None
        try:
            max_trades_i = int(float(max_trades)) if max_trades is not None and str(max_trades).strip() != "" else None
            if max_trades_i is not None and max_trades_i <= 0:
                max_trades_i = None
        except (TypeError, ValueError):
            max_trades_i = None

        daily_loss = cfg.get("dailyMaxLoss")
        daily_loss_f: float | None
        try:
            daily_loss_f = float(daily_loss) if daily_loss is not None and str(daily_loss).strip() != "" else None
            if daily_loss_f is not None and daily_loss_f <= 0:
                daily_loss_f = None
        except (TypeError, ValueError):
            daily_loss_f = None

        max_entries = _i("maxEntries", "tradeCount", default=4)
        initial_lots = _i("initialLots", "lotsPerEntry", default=2)
        add_lots = _i("addLots", default=1)
        raw_el = cfg.get("entryLots")
        parsed_el: list[int] | None = None
        if isinstance(raw_el, list) and raw_el:
            try:
                parsed_el = [max(1, int(float(x))) for x in raw_el]
            except (TypeError, ValueError):
                parsed_el = None

        return cls(
            entry_trigger=_f("entryTrigger", "gap", default=191.0),
            strike_offset=_f("strikeOffset", default=200.0),
            initial_lots=initial_lots,
            add_lots=add_lots,
            averaging_gap=_f("averagingGap", "offset", default=45.0),
            max_entries=max_entries,
            tp1_pts=_f("target1Points", default=45.0),
            tp1_pts_initial=_f("firstEntryTp1Points", "target1PointsInitial", default=70.0),
            tp2_trail=_f("tp2TrailPoints", default=30.0),
            stop_distance=_f("stopDistance", default=191.0),
            re_entry_enabled=bool(cfg.get("reEntryEnabled", True)),
            re_entry_gap=_f("reEntryGap", default=70.0),
            max_re_entries=max_re_i,
            call_enabled=call_on,
            put_enabled=put_on,
            first_entry_enabled=bool(cfg.get("firstEntryEnabled", True)),
            max_trades_per_day=max_trades_i,
            daily_max_loss=daily_loss_f,
            entry_lots=parsed_el or [],
        )


def normalize_entry_lots(
    raw: list[int] | None,
    *,
    max_entries: int,
    initial_lots: int = 2,
    add_lots: int = 1,
) -> list[int]:
    n = max(1, int(max_entries))
    if raw:
        out = [max(1, int(x)) for x in raw[:n]]
    else:
        out = [max(1, initial_lots)] + [max(1, add_lots)] * max(0, n - 1)
    while len(out) < n:
        out.append(out[-1] if out else max(1, add_lots))
    return out[:n]


def lots_for_entry(p: TrendParams, entry_index: int) -> int:
    idx = max(0, int(entry_index))
    if idx < len(p.entry_lots):
        return max(1, int(p.entry_lots[idx]))
    if p.entry_lots:
        return max(1, int(p.entry_lots[-1]))
    return max(1, p.initial_lots if idx == 0 else p.add_lots)


def avg_lots_filled(p: TrendParams, entries_filled: int) -> int:
    n = max(1, int(entries_filled))
    if n <= 1:
        return 0
    return sum(lots_for_entry(p, i) for i in range(1, n))


@dataclass
class OpenCycle:
    cycle_id: int
    side: str
    cycle_base: float
    first_entry: float
    lots: int
    t1_level: float
    t1_level_avg: float = 0.0
    t1_level_core: float = 0.0
    t1_done: bool = False
    avg_t1_done: bool = False
    core_t1_done: bool = False
    sl_level: float = 0.0
    cycle_extreme: float | None = None
    trail_extreme: float | None = None
    entry_kind: EntryKind = EntryKind.INITIAL
    entries_filled: int = 1
    adaptive_ref: float | None = None
    option_strike: float | None = None
    """Lots from initial/re-entry — TP1 partial + TP2 trail eligible."""
    core_lots: int = 0
    """Lots from averaging adds — exit at TP1 only, no TP2 trail."""
    avg_lots: int = 0


@dataclass
class EngineState:
    base_price: float | None = None
    open_cycle: OpenCycle | None = None
    wait_reentry_side: str | None = None
    reentry_anchor: float | None = None
    reentry_cycle_base: float | None = None
    re_entry_count: int = 0
    trades_today: int = 0
    daily_pnl_points: float = 0.0
    next_cycle_id: int = 1
    session_blocked: bool = False
    initial_entry_consumed: bool = False
    adaptive_high: float | None = None
    adaptive_low: float | None = None


@dataclass
class BarSlice:
    time: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    prev_close: float | None = None


@dataclass
class Signal:
    kind: SignalKind
    side: str
    price: float
    lots: int
    cycle_base: float
    first_entry: float
    t1_level: float
    strike: float
    entry_kind: EntryKind
    exit_reason: str = ""
    cycle_id: int = 0
    close_lots: int = 0
    note: str = ""
    adaptive_extreme: float | None = None
    sl_level: float | None = None


@dataclass
class TradeLogRow:
    date: str
    time: str
    cycle_id: int
    side: str
    action: str
    entry_type: str
    index_price: float
    strike: float
    lots: int
    tp1: float | None
    tp2: float | None
    stop_loss: float | None
    exit_price: float | None
    exit_reason: str
    trade_pnl: float
    running_pnl: float


def crossed(prev: float | None, cur: float, level: float) -> bool:
    if prev is None:
        return False
    return (prev - level) * (cur - level) <= 0


def crossed_down(prev: float | None, low: float, level: float) -> bool:
    if prev is None:
        return False
    return prev > level and low <= level


def crossed_up(prev: float | None, high: float, level: float) -> bool:
    if prev is None:
        return False
    return prev < level and high >= level


def strike_from_index(index_level: float, strike_offset: float) -> float:
    """Nearest exchange strike to index level (averaging entries)."""
    _ = strike_offset  # legacy signature; step is SENSEX_STRIKE_STEP
    return nearest_strike(index_level)


SENSEX_STRIKE_STEP = 100.0


def nearest_strike(index_level: float, strike_step: float = SENSEX_STRIKE_STEP) -> float:
    """Round index to nearest valid option strike (averaging entries only)."""
    step = max(50.0, float(strike_step))
    return round(float(index_level) / step) * step


def strike_ceil(index_level: float, strike_step: float = SENSEX_STRIKE_STEP) -> float:
    """Nearest higher strike on grid (CALL initial / re-entry after offset)."""
    step = max(50.0, float(strike_step))
    return math.ceil(float(index_level) / step) * step


def strike_floor(index_level: float, strike_step: float = SENSEX_STRIKE_STEP) -> float:
    """Nearest lower strike on grid (PUT initial / re-entry after offset)."""
    step = max(50.0, float(strike_step))
    return math.floor(float(index_level) / step) * step


def strike_from_trigger(
    trigger_price: float,
    side: str,
    strike_offset: float,
    strike_step: float = SENSEX_STRIKE_STEP,
) -> float:
    """Initial / re-entry: offset from index, then directional round to strike grid."""
    su = (side or "").upper()
    raw = float(trigger_price) - float(strike_offset) if su == "PUT" else float(trigger_price) + float(strike_offset)
    if su == "PUT":
        return strike_floor(raw, strike_step)
    return strike_ceil(raw, strike_step)


def resolve_signal_strike(
    *,
    side: str,
    index_price: float,
    entry_kind: EntryKind,
    strike_offset: float,
    strike_step: float = SENSEX_STRIKE_STEP,
) -> float:
    if entry_kind == EntryKind.AVERAGE:
        return nearest_strike(index_price, strike_step)
    return strike_from_trigger(index_price, side, strike_offset, strike_step)


def cycle_option_strike(oc: OpenCycle, p: TrendParams) -> float:
    if oc.option_strike is not None and oc.option_strike > 0:
        return float(oc.option_strike)
    return strike_from_trigger(oc.first_entry, oc.side, p.strike_offset)


def cycle_sl(side: str, cycle_base: float, p: TrendParams) -> float:
    """SL from cycle reference (day base for initial, adaptive extreme for re-entry)."""
    if side == "CALL":
        return float(cycle_base) - p.stop_distance
    return float(cycle_base) + p.stop_distance


def cycle_sl_for_open(oc: OpenCycle, p: TrendParams) -> float:
    if oc.sl_level > 0:
        return float(oc.sl_level)
    return open_cycle_sl_level(oc.side, oc.first_entry, p, entry_kind=oc.entry_kind, adaptive_ref=oc.adaptive_ref)


def tp1_level_for(side: str, first_entry: float, pts: float) -> float:
    if side == "CALL":
        return float(first_entry) + float(pts)
    return float(first_entry) - float(pts)


def open_cycle_sl_level(
    side: str,
    first_entry: float,
    p: TrendParams,
    *,
    entry_kind: EntryKind,
    adaptive_ref: float | None,
) -> float:
    """Initial SL: first entry ± stop. Re-entry: adaptive extreme ± stop."""
    if entry_kind == EntryKind.REENTRY and adaptive_ref is not None:
        return cycle_sl(side, float(adaptive_ref), p)
    if side == "CALL":
        return float(first_entry) - p.stop_distance
    return float(first_entry) + p.stop_distance


def _update_cycle_sl_trail(oc: OpenCycle, bar: BarSlice, p: TrendParams) -> None:
    """Re-entry cycles trail SL with adaptive extreme; after core TP1 initial cycles trail too."""
    if oc.entry_kind != EntryKind.REENTRY and not oc.core_t1_done:
        return
    side = oc.side
    if side == "CALL":
        oc.cycle_extreme = max(oc.cycle_extreme or oc.first_entry, bar.high, bar.close)
        trailed = float(oc.cycle_extreme) - p.stop_distance
        oc.sl_level = max(float(oc.sl_level), trailed)
    else:
        oc.cycle_extreme = min(oc.cycle_extreme or oc.first_entry, bar.low, bar.close)
        trailed = float(oc.cycle_extreme) + p.stop_distance
        oc.sl_level = min(float(oc.sl_level), trailed)


def _bump_sl_after_core_tp1(oc: OpenCycle, p: TrendParams) -> None:
    if oc.side == "CALL":
        oc.sl_level = float(oc.sl_level) + p.tp1_pts_initial
    else:
        oc.sl_level = float(oc.sl_level) - p.tp1_pts_initial


def _new_open_cycle(
    *,
    cycle_id: int,
    side: str,
    cycle_base: float,
    first_entry: float,
    lots: int,
    p: TrendParams,
    entry_kind: EntryKind,
    trail_extreme: float,
    option_strike: float | None,
    adaptive_ref: float | None,
) -> OpenCycle:
    t1_avg = tp1_level_for(side, first_entry, p.tp1_pts)
    t1_core = tp1_level_for(side, first_entry, p.tp1_pts_initial)
    sl = open_cycle_sl_level(side, first_entry, p, entry_kind=entry_kind, adaptive_ref=adaptive_ref)
    return OpenCycle(
        cycle_id=cycle_id,
        side=side,
        cycle_base=cycle_base,
        first_entry=first_entry,
        lots=lots,
        t1_level=t1_core,
        t1_level_avg=t1_avg,
        t1_level_core=t1_core,
        sl_level=sl,
        cycle_extreme=first_entry,
        trail_extreme=trail_extreme,
        entry_kind=entry_kind,
        entries_filled=1,
        adaptive_ref=adaptive_ref,
        option_strike=option_strike,
        core_lots=lots,
        avg_lots=0,
    )


def _update_adaptive_extremes(state: EngineState, bar: BarSlice, base: float, p: TrendParams) -> None:
    ce_trig = base + p.entry_trigger
    pe_trig = base - p.entry_trigger
    if bar.high >= ce_trig or state.open_cycle is not None and state.open_cycle.side == "CALL":
        state.adaptive_high = max(state.adaptive_high or bar.high, bar.high)
    if bar.low <= pe_trig or state.open_cycle is not None and state.open_cycle.side == "PUT":
        state.adaptive_low = min(state.adaptive_low or bar.low, bar.low)
    if state.wait_reentry_side == "CALL" and state.reentry_cycle_base is not None:
        state.adaptive_high = max(state.adaptive_high or state.reentry_cycle_base, bar.high, state.reentry_cycle_base)
    if state.wait_reentry_side == "PUT" and state.reentry_cycle_base is not None:
        state.adaptive_low = min(state.adaptive_low or state.reentry_cycle_base, bar.low, state.reentry_cycle_base)


def entry_count_from_lots(lots: int, p: TrendParams) -> int:
    lots = max(0, int(lots))
    acc = 0
    for i in range(p.max_entries):
        acc += lots_for_entry(p, i)
        if lots <= acc:
            return i + 1
    return p.max_entries


def next_add_level(side: str, first_entry: float, entry_count: int, p: TrendParams) -> float:
    if side == "CALL":
        return float(first_entry) - p.averaging_gap * float(entry_count)
    return float(first_entry) + p.averaging_gap * float(entry_count)


def tp1_close_lots(p: TrendParams) -> int:
    """Book one lot at TP1; remaining core lots trail to TP2."""
    core = lots_for_entry(p, 0)
    if core <= 1:
        return core
    return 1


def _risk_blocked(state: EngineState, p: TrendParams) -> bool:
    if state.session_blocked:
        return True
    if p.max_trades_per_day is not None and state.trades_today >= p.max_trades_per_day:
        return True
    if p.daily_max_loss is not None and state.daily_pnl_points <= -abs(p.daily_max_loss):
        return True
    return False


def _mk_open_signal(
    *,
    side: str,
    price: float,
    cycle_base: float,
    first_entry: float,
    lots: int,
    p: TrendParams,
    cycle_id: int,
    entry_kind: EntryKind,
) -> Signal:
    t1_core = tp1_level_for(side, first_entry, p.tp1_pts_initial)
    return Signal(
        kind=SignalKind.OPEN_INITIAL if entry_kind != EntryKind.AVERAGE else SignalKind.OPEN_AVERAGE,
        side=side,
        price=price,
        lots=lots,
        cycle_base=cycle_base,
        first_entry=first_entry,
        t1_level=t1_core,
        strike=resolve_signal_strike(
            side=side,
            index_price=price,
            entry_kind=entry_kind,
            strike_offset=p.strike_offset,
        ),
        entry_kind=entry_kind,
        cycle_id=cycle_id,
    )


def process_bar(
    state: EngineState,
    p: TrendParams,
    bar: BarSlice,
    *,
    session_end: bool = False,
) -> tuple[EngineState, list[Signal]]:
    """Process one bar; uses prev_close + OHLC without future data."""
    signals: list[Signal] = []
    prev = bar.prev_close
    px = bar.close
    hi = bar.high
    lo = bar.low

    if session_end and state.open_cycle is not None:
        c = state.open_cycle
        signals.append(
            Signal(
                kind=SignalKind.CLOSE_SESSION,
                side=c.side,
                price=px,
                lots=c.lots,
                cycle_base=c.cycle_base,
                first_entry=c.first_entry,
                t1_level=c.t1_level,
                strike=cycle_option_strike(c, p),
                entry_kind=c.entry_kind,
                exit_reason="SESSION_END",
                cycle_id=c.cycle_id,
                sl_level=float(c.sl_level),
            )
        )
        state.open_cycle = None
        state.wait_reentry_side = None
        return state, signals

    base = float(state.base_price) if state.base_price is not None else None
    if base is not None:
        _update_adaptive_extremes(state, bar, base, p)

    oc = state.open_cycle
    if oc is not None:
        side = oc.side
        _update_cycle_sl_trail(oc, bar, p)
        sl_px = float(oc.sl_level)

        hit_sl = (
            (side == "CALL" and crossed_down(prev, lo, sl_px))
            or (side == "PUT" and crossed_up(prev, hi, sl_px))
        )
        if hit_sl:
            signals.append(
                Signal(
                    kind=SignalKind.CLOSE_SL,
                    side=side,
                    price=sl_px,
                    lots=oc.lots,
                    cycle_base=oc.cycle_base,
                    first_entry=oc.first_entry,
                    t1_level=oc.t1_level,
                    strike=cycle_option_strike(oc, p),
                    entry_kind=oc.entry_kind,
                    exit_reason="INDEX_SL",
                    cycle_id=oc.cycle_id,
                    sl_level=sl_px,
                )
            )
            state.open_cycle = None
            state.wait_reentry_side = None
            return state, signals

        if oc.entries_filled < p.max_entries and prev is not None:
            nxt = next_add_level(side, oc.first_entry, oc.entries_filled, p)
            add_hit = (
                (side == "CALL" and crossed_down(prev, lo, nxt))
                or (side == "PUT" and crossed_up(prev, hi, nxt))
            )
            if add_hit and (
                (side == "CALL" and nxt > sl_px) or (side == "PUT" and nxt < sl_px)
            ):
                add_lots_n = lots_for_entry(p, oc.entries_filled)
                avg_sig = _mk_open_signal(
                        side=side,
                        price=nxt,
                        cycle_base=oc.cycle_base,
                        first_entry=oc.first_entry,
                        lots=add_lots_n,
                        p=p,
                        cycle_id=oc.cycle_id,
                        entry_kind=EntryKind.AVERAGE,
                    )
                avg_sig.sl_level = float(oc.sl_level)
                signals.append(avg_sig)
                oc.avg_lots += add_lots_n
                oc.lots += add_lots_n
                oc.entries_filled += 1

        if not oc.avg_t1_done and oc.avg_lots > 0:
            avg_t1_hit = (
                (side == "CALL" and crossed_up(prev, hi, oc.t1_level_avg))
                or (side == "PUT" and crossed_down(prev, lo, oc.t1_level_avg))
            )
            if avg_t1_hit:
                avg_close = oc.avg_lots
                signals.append(
                    Signal(
                        kind=SignalKind.PARTIAL_TP1,
                        side=side,
                        price=oc.t1_level_avg,
                        lots=oc.lots,
                        close_lots=avg_close,
                        cycle_base=oc.cycle_base,
                        first_entry=oc.first_entry,
                        t1_level=oc.t1_level_avg,
                        strike=cycle_option_strike(oc, p),
                        entry_kind=EntryKind.AVERAGE,
                        cycle_id=oc.cycle_id,
                        exit_reason="TP1_AVG",
                        sl_level=float(oc.sl_level),
                    )
                )
                oc.lots -= avg_close
                oc.avg_lots = 0
                oc.avg_t1_done = True

        if not oc.core_t1_done and oc.core_lots > 0:
            core_t1_hit = (
                (side == "CALL" and crossed_up(prev, hi, oc.t1_level_core))
                or (side == "PUT" and crossed_down(prev, lo, oc.t1_level_core))
            )
            if core_t1_hit:
                core_tp1 = min(tp1_close_lots(p), oc.core_lots)
                if core_tp1 > 0:
                    lots_before = oc.lots
                    oc.core_lots -= core_tp1
                    oc.lots -= core_tp1
                    _bump_sl_after_core_tp1(oc, p)
                    _update_cycle_sl_trail(oc, bar, p)
                    signals.append(
                        Signal(
                            kind=SignalKind.PARTIAL_TP1,
                            side=side,
                            price=oc.t1_level_core,
                            lots=lots_before,
                            close_lots=core_tp1,
                            cycle_base=oc.cycle_base,
                            first_entry=oc.first_entry,
                            t1_level=oc.t1_level_core,
                            strike=cycle_option_strike(oc, p),
                            entry_kind=oc.entry_kind,
                            cycle_id=oc.cycle_id,
                            exit_reason="TP1",
                            sl_level=float(oc.sl_level),
                        )
                    )
                oc.core_t1_done = True
                oc.t1_done = True
                if oc.core_lots > 0:
                    oc.trail_extreme = hi if side == "CALL" else lo

        if oc.core_t1_done and oc.core_lots > 0:
            extreme = oc.trail_extreme if oc.trail_extreme is not None else px
            if side == "CALL":
                extreme = max(extreme, hi, px)
                trail_tp = extreme - p.tp2_trail
                oc.trail_extreme = extreme
                tp2_hit = crossed_down(prev, lo, trail_tp)
                if tp2_hit and extreme > trail_tp:
                    signals.append(
                        Signal(
                            kind=SignalKind.CLOSE_TP2,
                            side=side,
                            price=trail_tp,
                            lots=oc.core_lots,
                            close_lots=oc.core_lots,
                            cycle_base=oc.cycle_base,
                            first_entry=oc.first_entry,
                            t1_level=oc.t1_level,
                            strike=cycle_option_strike(oc, p),
                            entry_kind=oc.entry_kind,
                            exit_reason="TP2_TRAIL",
                            cycle_id=oc.cycle_id,
                            adaptive_extreme=extreme,
                            sl_level=float(oc.sl_level),
                        )
                    )
                    state.open_cycle = None
                    if p.re_entry_enabled and (
                        p.max_re_entries is None or state.re_entry_count < p.max_re_entries
                    ):
                        # Re-entry trigger = adaptive high − re_entry_gap (not TP2 trail price).
                        state.wait_reentry_side = "CALL"
                        state.reentry_anchor = extreme
                        state.reentry_cycle_base = extreme
                        state.adaptive_high = max(state.adaptive_high or extreme, extreme)
                        state.re_entry_count += 1
                    else:
                        state.wait_reentry_side = None
                    return state, signals
            else:
                extreme = min(extreme, lo, px)
                trail_tp = extreme + p.tp2_trail
                oc.trail_extreme = extreme
                tp2_hit = crossed_up(prev, hi, trail_tp)
                if tp2_hit and extreme < trail_tp:
                    signals.append(
                        Signal(
                            kind=SignalKind.CLOSE_TP2,
                            side=side,
                            price=trail_tp,
                            lots=oc.core_lots,
                            close_lots=oc.core_lots,
                            cycle_base=oc.cycle_base,
                            first_entry=oc.first_entry,
                            t1_level=oc.t1_level,
                            strike=cycle_option_strike(oc, p),
                            entry_kind=oc.entry_kind,
                            exit_reason="TP2_TRAIL",
                            cycle_id=oc.cycle_id,
                            adaptive_extreme=extreme,
                            sl_level=float(oc.sl_level),
                        )
                    )
                    state.open_cycle = None
                    if p.re_entry_enabled and (
                        p.max_re_entries is None or state.re_entry_count < p.max_re_entries
                    ):
                        # Re-entry trigger = adaptive low + re_entry_gap (not TP2 trail price).
                        state.wait_reentry_side = "PUT"
                        state.reentry_anchor = extreme
                        state.reentry_cycle_base = extreme
                        state.adaptive_low = min(state.adaptive_low or extreme, extreme)
                        state.re_entry_count += 1
                    else:
                        state.wait_reentry_side = None
                    return state, signals

        state.open_cycle = oc
        return state, signals

    if prev is None or base is None or _risk_blocked(state, p):
        return state, signals

    if state.wait_reentry_side == "CALL" and p.call_enabled:
        # ADP high − gap (live adaptive high keeps ratcheting after TP2).
        adp = float(state.adaptive_high or state.reentry_cycle_base or state.reentry_anchor or 0)
        cbase = float(state.reentry_cycle_base or adp or base)
        re_trig = adp - p.re_entry_gap
        re_sl = cycle_sl("CALL", cbase, p)
        if adp > 0 and re_trig > re_sl and crossed_down(prev, lo, re_trig):
            cid = state.next_cycle_id
            state.next_cycle_id += 1
            sig = _mk_open_signal(
                side="CALL",
                price=re_trig,
                cycle_base=cbase,
                first_entry=re_trig,
                lots=lots_for_entry(p, 0),
                p=p,
                cycle_id=cid,
                entry_kind=EntryKind.REENTRY,
            )
            signals.append(sig)
            state.open_cycle = _new_open_cycle(
                cycle_id=cid,
                side="CALL",
                cycle_base=cbase,
                first_entry=re_trig,
                lots=lots_for_entry(p, 0),
                p=p,
                entry_kind=EntryKind.REENTRY,
                trail_extreme=px,
                option_strike=sig.strike,
                adaptive_ref=cbase,
            )
            sig.sl_level = float(state.open_cycle.sl_level)
            state.wait_reentry_side = None
            state.trades_today += 1
            return state, signals

    if state.wait_reentry_side == "PUT" and p.put_enabled:
        # ADP low + gap (live adaptive low keeps ratcheting after TP2).
        adp = float(state.adaptive_low or state.reentry_cycle_base or state.reentry_anchor or 0)
        cbase = float(state.reentry_cycle_base or adp or base)
        re_trig = adp + p.re_entry_gap
        re_sl = cycle_sl("PUT", cbase, p)
        if adp > 0 and re_trig < re_sl and crossed_up(prev, hi, re_trig):
            cid = state.next_cycle_id
            state.next_cycle_id += 1
            sig = _mk_open_signal(
                side="PUT",
                price=re_trig,
                cycle_base=cbase,
                first_entry=re_trig,
                lots=lots_for_entry(p, 0),
                p=p,
                cycle_id=cid,
                entry_kind=EntryKind.REENTRY,
            )
            signals.append(sig)
            state.open_cycle = _new_open_cycle(
                cycle_id=cid,
                side="PUT",
                cycle_base=cbase,
                first_entry=re_trig,
                lots=lots_for_entry(p, 0),
                p=p,
                entry_kind=EntryKind.REENTRY,
                trail_extreme=px,
                option_strike=sig.strike,
                adaptive_ref=cbase,
            )
            sig.sl_level = float(state.open_cycle.sl_level)
            state.wait_reentry_side = None
            state.trades_today += 1
            return state, signals

    if state.wait_reentry_side:
        return state, signals

    if not p.first_entry_enabled or state.initial_entry_consumed:
        return state, signals

    ce_trig = base + p.entry_trigger
    pe_trig = base - p.entry_trigger
    ce_cross = p.call_enabled and crossed_up(prev, hi, ce_trig)
    pe_cross = p.put_enabled and crossed_down(prev, lo, pe_trig)

    side_to_open: str | None = None
    if ce_cross and not pe_cross:
        side_to_open = "CALL"
    elif pe_cross and not ce_cross:
        side_to_open = "PUT"
    elif ce_cross and pe_cross:
        side_to_open = "CALL" if px >= base else "PUT"

    if side_to_open:
        trig = ce_trig if side_to_open == "CALL" else pe_trig
        cid = state.next_cycle_id
        state.next_cycle_id += 1
        sig = _mk_open_signal(
            side=side_to_open,
            price=trig,
            cycle_base=base,
            first_entry=trig,
            lots=lots_for_entry(p, 0),
            p=p,
            cycle_id=cid,
            entry_kind=EntryKind.INITIAL,
        )
        signals.append(sig)
        state.open_cycle = _new_open_cycle(
            cycle_id=cid,
            side=side_to_open,
            cycle_base=base,
            first_entry=trig,
            lots=lots_for_entry(p, 0),
            p=p,
            entry_kind=EntryKind.INITIAL,
            trail_extreme=px,
            option_strike=sig.strike,
            adaptive_ref=base,
        )
        sig.sl_level = float(state.open_cycle.sl_level)
        state.initial_entry_consumed = True
        state.trades_today += 1

    return state, signals


def points_pnl(side: str, entry: float, exit_px: float, lots: int) -> float:
    raw = (exit_px - entry) if side == "CALL" else (entry - exit_px)
    return round(raw * lots, 2)
