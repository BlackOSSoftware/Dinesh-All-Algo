"""
SENSEX Adaptive Trend Averaging Strategy — index-level triggers, averaging ladder,
TP1 partial (initial lots only), trailing TP2, capped re-entries.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.models import StrategySettings, TradePosition
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.bfo_options import resolve_bfo_option
from app.services.sensex_option_buy import (
    LEG_SOB,
    _angel_headers,
    _base_from_cfg,
    _close_sob,
    _in_trading_window,
    _ist_tz,
    _lot_multiplier,
    _now_ist,
    _parse_order_book_list,
    _past_or_at_session_end,
    _poll_live_add_fill,
    _poll_live_entry_fill,
    _sob_is_sensex_pos,
    _synthetic_option_mark,
)
from app.services.sensex_trend_core import (
    BarSlice,
    EngineState,
    EntryKind,
    OpenCycle,
    Signal,
    SignalKind,
    TrendParams,
    avg_lots_filled,
    nearest_strike,
    process_bar,
    strike_from_trigger,
    tp1_close_lots,
    open_cycle_sl_level,
    tp1_level_for,
)

LOG = logging.getLogger(__name__)


def _strike_for_entry(
    *,
    side: str,
    index_level: float,
    entry_kind: EntryKind,
    strike_offset: float,
) -> float:
    if entry_kind == EntryKind.AVERAGE:
        return nearest_strike(index_level)
    return strike_from_trigger(index_level, side, strike_offset)


def _persist_runtime(db: Session, user_id: int, runtime: dict[str, Any]) -> None:
    tr.merge_strategy_runtime(db, user_id, runtime)


def _qty_for_lots(lots: int, cfg: dict[str, Any]) -> int:
    return max(1, int(lots)) * _lot_multiplier(cfg)


def _place_buy(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    *,
    side: str,
    index_ltp: float,
    option_strike: float,
    lots: int,
    cycle_base: float,
    first_entry_index: float,
    t1_index: float,
) -> bool:
    """Place entry/add order. Returns True if position row created (or paper filled)."""
    uid = st_row.user_id
    mode = (st_row.trading_mode or "PAPER").upper()
    su = "PUT" if side.upper() == "PUT" else "CALL"
    opt_side = "PE" if su == "PUT" else "CE"
    qty = _qty_for_lots(lots, cfg)
    exch = (settings.angel_option_exchange or "BFO").upper()
    product = (settings.angel_option_product_type or "CARRYFORWARD").upper()
    syn_entry = max(5.0, min(5000.0, float(cfg.get("offset") or 45) * 0.1))

    if mode == "LIVE":
        resolved = resolve_bfo_option(option_strike, opt_side)
        if resolved is None:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                strike=option_strike,
                quantity=qty,
                message="LIVE: no BFO instrument mapping",
            )
            return False
        qty = max(1, int(resolved.lotsize)) * max(1, int(lots))
        try:
            raw = angel_orders.place_market_order(
                exchange=exch,
                tradingsymbol=resolved.tradingsymbol,
                symboltoken=resolved.token,
                transaction_type="BUY",
                quantity=qty,
                product_type=product,
                timeout_sec=min(float(settings.angel_request_timeout_sec or 5.0), 8.0),
                **_angel_headers(),
            )
        except RuntimeError as e:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                strike=option_strike,
                quantity=qty,
                message=str(e)[:900],
            )
            return False
        data = raw.get("data") if isinstance(raw, dict) else None
        oid = ""
        if isinstance(data, dict):
            oid = str(data.get("orderid") or data.get("orderId") or "")
        msg = str(raw.get("message") or raw.get("Message") or "")
        if not oid:
            oid, _ok, ack_msg = angel_orders.extract_place_ack(raw)
            msg = msg or ack_msg
        if not oid:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                status="REJECTED",
                message=msg or json.dumps(raw)[:900],
            )
            return False

        outcome = angel_orders.await_order_terminal(
            order_id=oid,
            timeout_sec=min(6.0, float(settings.angel_request_timeout_sec or 15.0)),
            poll_interval_sec=0.08,
            cancel_if_unfilled=True,
            **_angel_headers(),
        )
        if not outcome.filled:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                strike=option_strike,
                quantity=qty,
                order_id=oid,
                status=outcome.status,
                message=(f"Broker {outcome.status}: {outcome.message or msg}")[:900],
            )
            return False

        fill_px = float(outcome.average_price or 0.0)
        if fill_px <= 0:
            fill_px = syn_entry
        pos = TradePosition(
            user_id=uid,
            leg_id=LEG_SOB,
            trading_mode="LIVE",
            side=su,
            range_level=float(cycle_base),
            strike=float(first_entry_index),
            tp=None,
            lots=max(1, lots),
            quantity=qty,
            put_sl_pts=int(round(t1_index)),
            call_sl_pts=None,
            sl_mode="sensex",
            underlying_at_entry=index_ltp,
            entry_price=fill_px,
            exchange=exch,
            trading_symbol=resolved.tradingsymbol,
            symbol_token=str(resolved.token),
            order_id=oid,
            unique_order_id=None,
            last_order_message=(outcome.message or msg or "FILLED")[:500],
        )
        tr.create_open_position(db, pos)
        tr.append_trading_log(
            db,
            user_id=uid,
            mode="LIVE",
            leg=LEG_SOB,
            action="ORDER_FILLED",
            symbol=resolved.tradingsymbol,
            strike=resolved.strike,
            quantity=qty,
            entry_price=fill_px,
            order_id=oid,
            status="COMPLETE",
            message=f"SENSEX {su} FILLED @ {fill_px:g} · index≈{first_entry_index:g} cycle_base={cycle_base:g}",
        )
        return True

    pos = TradePosition(
        user_id=uid,
        leg_id=LEG_SOB,
        trading_mode="PAPER",
        side=su,
        range_level=float(cycle_base),
        strike=float(first_entry_index),
        tp=None,
        lots=max(1, lots),
        quantity=qty,
        put_sl_pts=int(round(t1_index)),
        call_sl_pts=None,
        sl_mode="sensex",
        underlying_at_entry=index_ltp,
        entry_price=syn_entry,
        exchange=exch,
        trading_symbol=f"{round(option_strike):g} {opt_side}",
        symbol_token=None,
        order_id=None,
        unique_order_id=None,
        last_order_message="PAPER_SIM",
    )
    tr.create_open_position(db, pos)
    tr.append_trading_log(
        db,
        user_id=uid,
        mode="PAPER",
        leg=LEG_SOB,
        action="ENTRY",
        symbol=pos.trading_symbol,
        strike=option_strike,
        quantity=qty,
        entry_price=syn_entry,
        status="FILLED",
        message=f"SENSEX {su} · trigger {first_entry_index:g} · strike {round(option_strike):g} {opt_side} · T1 {t1_index:g}",
    )
    return True


def _place_add_lot(
    db: Session,
    pos: TradePosition,
    cfg: dict[str, Any],
    p: TrendParams,
    index_ltp: float,
    *,
    add_lots: int,
) -> bool:
    mode = (pos.trading_mode or "PAPER").upper()
    opt_side = "PE" if (pos.side or "").upper() == "PUT" else "CE"
    option_strike = nearest_strike(index_ltp)
    add_qty = _qty_for_lots(add_lots, cfg)
    exch = (settings.angel_option_exchange or "BFO").upper()
    product = (settings.angel_option_product_type or "CARRYFORWARD").upper()
    syn_add = max(5.0, min(5000.0, float(cfg.get("offset") or 45) * 0.1))

    if mode == "LIVE":
        resolved = resolve_bfo_option(option_strike, opt_side)
        if resolved is None:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                status="REJECTED",
                message="SENSEX add: no BFO mapping",
            )
            return False
        add_qty = max(1, int(resolved.lotsize)) * add_lots
        try:
            raw = angel_orders.place_market_order(
                exchange=exch,
                tradingsymbol=resolved.tradingsymbol,
                symboltoken=resolved.token,
                transaction_type="BUY",
                quantity=add_qty,
                product_type=product,
                timeout_sec=min(float(settings.angel_request_timeout_sec or 5.0), 8.0),
                **_angel_headers(),
            )
        except RuntimeError as e:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                status="REJECTED",
                message=str(e)[:900],
            )
            return False
        oid, _ok, ack_msg = angel_orders.extract_place_ack(raw)
        if not oid:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                status="REJECTED",
                message=ack_msg or "add: no order id",
            )
            return False
        outcome = angel_orders.await_order_terminal(
            order_id=oid,
            timeout_sec=min(5.0, float(settings.angel_request_timeout_sec or 15.0)),
            poll_interval_sec=0.08,
            cancel_if_unfilled=True,
            **_angel_headers(),
        )
        if not outcome.filled:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                order_id=oid,
                status=outcome.status,
                message=f"Add lot {outcome.status}: {outcome.message or ack_msg}"[:900],
            )
            return False
        avg = float(outcome.average_price or 0) or syn_add
        old_lots = max(1, int(pos.lots))
        old_qty = int(pos.quantity)
        old_ep = float(pos.entry_price or 0.0)
        new_lots = old_lots + add_lots
        new_qty = old_qty + add_qty
        new_ep = (old_ep * old_qty + avg * add_qty) / max(1, new_qty) if old_ep > 0 else avg
        tr.update_position_fields(
            db,
            pos,
            lots=new_lots,
            quantity=new_qty,
            entry_price=new_ep,
            unique_order_id=None,
            last_order_message=f"ADD_FILLED lots={new_lots}",
        )
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode="LIVE",
            leg=LEG_SOB,
            action="LOT_ADDED",
            symbol=resolved.tradingsymbol,
            quantity=add_qty,
            entry_price=avg,
            order_id=oid,
            status="COMPLETE",
            message=f"SENSEX averaging add FILLED; total lots={new_lots}",
        )
        return True

    old_lots = max(1, int(pos.lots))
    old_qty = int(pos.quantity)
    old_ep = float(pos.entry_price or 0.0)
    new_lots = old_lots + add_lots
    new_qty = old_qty + add_qty
    new_ep = (old_ep * old_qty + syn_add * add_qty) / max(1, new_qty) if old_ep > 0 else syn_add
    tr.update_position_fields(
        db,
        pos,
        lots=new_lots,
        quantity=new_qty,
        entry_price=new_ep,
        trading_symbol=f"{round(option_strike):g} {opt_side}",
    )
    tr.append_trading_log(
        db,
        user_id=pos.user_id,
        mode=pos.trading_mode,
        leg=LEG_SOB,
        action="LOT_ADDED",
        symbol=f"{round(option_strike):g} {opt_side}",
        strike=option_strike,
        quantity=add_qty,
        entry_price=syn_add,
        message=f"SENSEX AVG @ index {index_ltp:g} · strike {round(option_strike):g} {opt_side} · total lots={new_lots}",
    )
    return True


def _partial_exit_lots(
    db: Session,
    pos: TradePosition,
    cfg: dict[str, Any],
    p: TrendParams,
    index_ltp: float,
    close_lots: int,
) -> bool:
    lots = max(1, int(pos.lots))
    qty = int(pos.quantity)
    per = max(1, qty // lots)
    close_lots = max(1, min(close_lots, lots - 1))
    closed_qty = per * close_lots
    rem_lots = lots - close_lots
    rem_qty = per * rem_lots
    mark = _synthetic_option_mark(pos, index_ltp)
    entry = float(pos.entry_price or 0.0)
    pnl_part = (mark - entry) * closed_qty if entry > 0 else 0.0

    mode = (pos.trading_mode or "PAPER").upper()
    if mode == "LIVE" and pos.trading_symbol and pos.symbol_token:
        try:
            raw = angel_orders.place_market_order(
                exchange=(pos.exchange or "BFO").upper(),
                tradingsymbol=pos.trading_symbol,
                symboltoken=str(pos.symbol_token),
                transaction_type="SELL",
                quantity=closed_qty,
                product_type=(settings.angel_option_product_type or "CARRYFORWARD").upper(),
                timeout_sec=min(float(settings.angel_request_timeout_sec or 5.0), 8.0),
                **_angel_headers(),
            )
        except RuntimeError as e:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                status="REJECTED",
                message=f"T1 partial SELL failed: {e}"[:900],
            )
            return False
        oid, _ok, ack_msg = angel_orders.extract_place_ack(raw)
        if not oid:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                status="REJECTED",
                message=f"T1 partial SELL no order id: {ack_msg}"[:900],
            )
            return False
        outcome = angel_orders.await_order_terminal(
            order_id=oid,
            timeout_sec=min(5.0, float(settings.angel_request_timeout_sec or 15.0)),
            poll_interval_sec=0.08,
            cancel_if_unfilled=True,
            **_angel_headers(),
        )
        if not outcome.filled:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                order_id=oid,
                status=outcome.status,
                message=f"T1 partial SELL {outcome.status}: {outcome.message or ack_msg}"[:900],
            )
            return False
        if float(outcome.average_price or 0) > 0:
            mark = float(outcome.average_price)
            pnl_part = (mark - entry) * closed_qty if entry > 0 else 0.0
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode="LIVE",
            leg=LEG_SOB,
            action="ORDER_FILLED",
            quantity=closed_qty,
            exit_price=mark,
            order_id=oid,
            status="COMPLETE",
            message=f"T1 partial SELL FILLED {close_lots} lot(s) @ {mark:g}",
        )

    tr.update_position_fields(db, pos, lots=rem_lots, quantity=rem_qty, sl_mode="sensex_t1_done")
    tr.append_trading_log(
        db,
        user_id=pos.user_id,
        mode=pos.trading_mode,
        leg=LEG_SOB,
        action="T1_PARTIAL",
        quantity=closed_qty,
        entry_price=entry,
        exit_price=mark,
        pnl=pnl_part,
        message=f"T1 partial closed {close_lots} lot(s); remaining {rem_lots}",
    )
    return True


def _open_initial(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    p: TrendParams,
    *,
    side: str,
    index_ltp: float,
    cycle_base: float,
    first_entry: float,
    lots: int,
    entry_kind: EntryKind = EntryKind.INITIAL,
) -> bool:
    su = side.upper()
    if su == "CALL":
        t1 = first_entry + p.tp1_pts_initial
    else:
        t1 = first_entry - p.tp1_pts_initial
    opt = _strike_for_entry(
        side=su, index_level=first_entry, entry_kind=entry_kind, strike_offset=p.strike_offset
    )
    if _place_buy(
        db,
        st_row,
        cfg,
        side=su,
        index_ltp=index_ltp,
        option_strike=opt,
        lots=lots,
        cycle_base=cycle_base,
        first_entry_index=first_entry,
        t1_index=t1,
    ):
        runtime = tr.load_strategy_runtime(cfg)
        runtime["trail_extreme"] = float(index_ltp)
        runtime["re_entry_count"] = int(runtime.get("re_entry_count") or 0)
        runtime["flat_mode"] = None
        _persist_runtime(db, st_row.user_id, runtime)
        return True
    return False


def _flat_mode_from_state(state: EngineState) -> str | None:
    if state.wait_reentry_side == "CALL":
        return "WAIT_REENTRY_CALL"
    if state.wait_reentry_side == "PUT":
        return "WAIT_REENTRY_PUT"
    return None


def _state_from_runtime(
    runtime: dict[str, Any],
    *,
    base_price: float,
    pos: TradePosition | None,
    p: TrendParams | None = None,
) -> EngineState:
    state = EngineState(
        base_price=float(base_price),
        re_entry_count=int(runtime.get("re_entry_count") or 0),
        next_cycle_id=int(runtime.get("next_cycle_id") or 1),
        trades_today=int(runtime.get("trades_today") or 0),
        daily_pnl_points=float(runtime.get("daily_pnl_points") or 0),
        session_blocked=bool(runtime.get("session_blocked")),
        initial_entry_consumed=bool(runtime.get("initial_entry_consumed")),
        adaptive_high=float(runtime["adaptive_high"]) if runtime.get("adaptive_high") is not None else None,
        adaptive_low=float(runtime["adaptive_low"]) if runtime.get("adaptive_low") is not None else None,
    )
    wait = runtime.get("flat_mode")
    if wait == "WAIT_REENTRY_CALL":
        state.wait_reentry_side = "CALL"
        state.reentry_anchor = float(runtime.get("reentry_anchor") or 0) or None
        state.reentry_cycle_base = float(runtime.get("reentry_cycle_base") or base_price)
    elif wait == "WAIT_REENTRY_PUT":
        state.wait_reentry_side = "PUT"
        state.reentry_anchor = float(runtime.get("reentry_anchor") or 0) or None
        state.reentry_cycle_base = float(runtime.get("reentry_cycle_base") or base_price)

    if pos is None:
        return state

    t1_done = str(pos.sl_mode or "") == "sensex_t1_done"
    trail = runtime.get("trail_extreme")
    lots = max(1, int(pos.lots or 1))
    entries_filled = max(1, int(runtime.get("entries_filled") or 1))
    core_lots = int(runtime.get("core_lots") or 0)
    avg_lots = int(runtime.get("avg_lots") or 0)
    if core_lots == 0 and avg_lots == 0:
        if t1_done:
            core_lots, avg_lots = lots, 0
        elif entries_filled == 1:
            core_lots, avg_lots = lots, 0
        elif p is not None:
            avg_lots = min(lots, avg_lots_filled(p, entries_filled))
            core_lots = max(0, lots - avg_lots)
        else:
            core_lots, avg_lots = lots, 0
    side_u = (pos.side or "CALL").upper()
    first_entry = float(pos.strike or 0)
    entry_kind = EntryKind.REENTRY if str(runtime.get("entry_kind") or "") == "REENTRY" else EntryKind.INITIAL
    adaptive_ref = float(runtime.get("adaptive_ref") or pos.range_level or base_price)
    t1_core = float(pos.put_sl_pts or 0) or (tp1_level_for(side_u, first_entry, p.tp1_pts_initial) if p else 0.0)
    t1_avg = float(runtime.get("t1_level_avg") or 0) or (tp1_level_for(side_u, first_entry, p.tp1_pts) if p else t1_core)
    sl_level = float(runtime.get("sl_level") or 0)
    if sl_level <= 0 and p is not None:
        sl_level = open_cycle_sl_level(side_u, first_entry, p, entry_kind=entry_kind, adaptive_ref=adaptive_ref)
    state.open_cycle = OpenCycle(
        cycle_id=int(runtime.get("cycle_id") or pos.id or 1),
        side=side_u,
        cycle_base=float(pos.range_level or base_price),
        first_entry=first_entry,
        lots=lots,
        t1_level=t1_core,
        t1_level_avg=t1_avg,
        t1_level_core=t1_core,
        t1_done=t1_done,
        avg_t1_done=bool(runtime.get("avg_t1_done")) or (avg_lots == 0 and entries_filled > 1),
        core_t1_done=t1_done,
        sl_level=sl_level,
        cycle_extreme=float(runtime.get("cycle_extreme") or first_entry),
        trail_extreme=float(trail) if trail is not None else None,
        entry_kind=entry_kind,
        entries_filled=entries_filled,
        adaptive_ref=adaptive_ref,
        core_lots=core_lots,
        avg_lots=avg_lots,
    )
    return state


def _runtime_from_state(runtime: dict[str, Any], state: EngineState) -> dict[str, Any]:
    runtime["flat_mode"] = _flat_mode_from_state(state)
    runtime["reentry_anchor"] = state.reentry_anchor
    runtime["reentry_cycle_base"] = state.reentry_cycle_base
    runtime["re_entry_count"] = state.re_entry_count
    runtime["next_cycle_id"] = state.next_cycle_id
    runtime["trades_today"] = state.trades_today
    runtime["daily_pnl_points"] = state.daily_pnl_points
    runtime["session_blocked"] = state.session_blocked
    runtime["initial_entry_consumed"] = state.initial_entry_consumed
    runtime["adaptive_high"] = state.adaptive_high
    runtime["adaptive_low"] = state.adaptive_low
    oc = state.open_cycle
    if oc is not None:
        runtime["cycle_id"] = oc.cycle_id
        runtime["trail_extreme"] = oc.trail_extreme
        runtime["entry_kind"] = oc.entry_kind.value
        runtime["entries_filled"] = oc.entries_filled
        runtime["adaptive_ref"] = oc.adaptive_ref
        runtime["core_lots"] = oc.core_lots
        runtime["avg_lots"] = oc.avg_lots
        runtime["sl_level"] = oc.sl_level
        runtime["t1_level_avg"] = oc.t1_level_avg
        runtime["t1_level_core"] = oc.t1_level_core
        runtime["avg_t1_done"] = oc.avg_t1_done
        runtime["core_t1_done"] = oc.core_t1_done
        runtime["cycle_extreme"] = oc.cycle_extreme
    else:
        runtime.pop("cycle_id", None)
        runtime["trail_extreme"] = None
        runtime.pop("entry_kind", None)
        runtime.pop("core_lots", None)
        runtime.pop("avg_lots", None)
        runtime.pop("sl_level", None)
        runtime.pop("t1_level_avg", None)
        runtime.pop("t1_level_core", None)
        runtime.pop("avg_t1_done", None)
        runtime.pop("core_t1_done", None)
        runtime.pop("cycle_extreme", None)
    return runtime


def _execute_core_signal(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    p: TrendParams,
    sig: Signal,
    index_ltp: float,
    *,
    pos: TradePosition | None,
) -> bool:
    """Apply signal. Returns False when a LIVE broker order was rejected (no state advance)."""
    uid = st_row.user_id

    if sig.kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE):
        if pos is not None:
            if sig.kind == SignalKind.OPEN_AVERAGE and not str(pos.unique_order_id or "").upper().startswith("ADD:"):
                return _place_add_lot(db, pos, cfg, p, index_ltp, add_lots=sig.lots)
            return True
        return _open_initial(
            db,
            st_row,
            cfg,
            p,
            side=sig.side,
            index_ltp=index_ltp,
            cycle_base=sig.cycle_base,
            first_entry=sig.first_entry,
            lots=sig.lots,
            entry_kind=sig.entry_kind,
        )

    if pos is None:
        return True

    if sig.kind == SignalKind.PARTIAL_TP1:
        close_lots = sig.close_lots or tp1_close_lots(p)
        if int(pos.lots) > close_lots:
            ok = _partial_exit_lots(db, pos, cfg, p, index_ltp, close_lots)
            if not ok:
                return False
            pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)
            if pos:
                tr.update_position_fields(db, pos, sl_mode="sensex_t1_done")
        else:
            tr.update_position_fields(db, pos, sl_mode="sensex_t1_done")
        return True

    if sig.kind in (SignalKind.CLOSE_TP2, SignalKind.CLOSE_SL, SignalKind.CLOSE_SESSION):
        reason = sig.exit_reason or sig.kind.value
        return bool(_close_sob(db, pos, reason, index_ltp))
    return True


def tick_sensex_adaptive_trend_session(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    index_ltp: float,
    prev: float | None,
) -> None:
    uid = st_row.user_id
    p = TrendParams.from_config(cfg)
    base = _base_from_cfg(cfg)
    if base is None:
        return

    now = _now_ist()
    start_s = str(cfg.get("startTime") or "09:15")
    end_s = str(cfg.get("endTime") or "15:30")
    auto_sq = str(cfg.get("autoSquareOffTime") or end_s)
    in_win = _in_trading_window(now, start_s, end_s)
    runtime = tr.load_strategy_runtime(cfg)

    pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)
    pending_reject_cleanup = bool(
        pos and pos.trading_mode == "LIVE" and float(pos.entry_price or 0) <= 0 and pos.order_id
    )
    if pending_reject_cleanup:
        _poll_live_entry_fill(db, pos)
    if pos and pos.trading_mode == "LIVE":
        _poll_live_add_fill(db, pos, cfg)

    pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)
    if pending_reject_cleanup and pos is None:
        # Entry never filled / broker rejected — wipe open-cycle runtime.
        runtime.update(
            {
                "flat_mode": None,
                "trail_extreme": None,
                "initial_entry_consumed": False,
                "core_lots": 0,
                "avg_lots": 0,
            }
        )
        for k in (
            "entry_kind",
            "sl_level",
            "t1_level_avg",
            "t1_level_core",
            "avg_t1_done",
            "core_t1_done",
            "cycle_extreme",
            "adaptive_ref",
            "cycle_id",
            "entries_filled",
        ):
            runtime.pop(k, None)
        _persist_runtime(db, uid, runtime)

    if str(cfg.get("slMode") or "auto") == "auto" and _past_or_at_session_end(now, auto_sq):
        while True:
            p2 = tr.get_open_position_by_leg(db, uid, LEG_SOB)
            if p2 is None:
                break
            if p2.trading_mode == "LIVE" and float(p2.entry_price or 0) <= 0 and p2.order_id:
                try:
                    angel_orders.cancel_order(
                        variety="NORMAL",
                        order_id=str(p2.order_id),
                        timeout_sec=min(float(settings.angel_request_timeout_sec or 5.0), 8.0),
                        **_angel_headers(),
                    )
                except RuntimeError:
                    pass
            _close_sob(db, p2, "AUTO_EXIT", index_ltp)
        runtime.clear()
        runtime.update({"flat_mode": None, "trail_extreme": None, "re_entry_count": 0})
        _persist_runtime(db, uid, runtime)
        return

    if pos and _sob_is_sensex_pos(pos):
        if pos.trading_mode == "LIVE" and float(pos.entry_price or 0) <= 0:
            _persist_runtime(db, uid, runtime)
            return
        if str(pos.unique_order_id or "").upper().startswith("ADD:"):
            _persist_runtime(db, uid, runtime)
            return

    mode_u = (st_row.trading_mode or "PAPER").upper()
    if mode_u != "PAPER" and not in_win and pos is None:
        _persist_runtime(db, uid, runtime)
        return

    if tr.leg_has_session_blocking_exit_today_ist(db, uid, LEG_SOB) and pos is None:
        _persist_runtime(db, uid, runtime)
        return

    runtime_before = deepcopy(runtime)
    state = _state_from_runtime(runtime, base_price=float(base), pos=pos, p=p)
    session_end = _past_or_at_session_end(now, auto_sq)
    bar = BarSlice(
        time=now.isoformat(),
        open=index_ltp,
        high=index_ltp,
        low=index_ltp,
        close=index_ltp,
        prev_close=float(prev) if prev is not None else float(base),
    )
    state, signals = process_bar(state, p, bar, session_end=session_end)

    broker_ok = True
    for sig in signals:
        pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)
        if not _execute_core_signal(db, st_row, cfg, p, sig, index_ltp, pos=pos):
            broker_ok = False
            break

    if not broker_ok:
        # Rejected LIVE order: do not advance strategy runtime (prevents phantom SL/TP).
        _persist_runtime(db, uid, runtime_before)
        return

    runtime = _runtime_from_state(runtime, state)
    _persist_runtime(db, uid, runtime)
