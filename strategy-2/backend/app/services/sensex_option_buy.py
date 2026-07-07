"""
SENSEX option-buy strategy: BASE from reference close, ±gap entry, ±offset adds,
BASE stop, T2 full exit, T1 partial. One leg id SOB (CALL or PUT), exclusive directions.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.models import StrategySettings, TradePosition
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.angel_quote import _truthy_status
from app.services.bfo_options import resolve_bfo_option

LOG = logging.getLogger(__name__)

LEG_SOB = "SOB"


def _ist_tz():
    try:
        return ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=5, minutes=30))


def _parse_hhmm(s: str) -> dt_time | None:
    raw = (s or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", raw)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mm <= 59):
        return None
    return dt_time(h, mm)


def _now_ist() -> datetime:
    return datetime.now(_ist_tz())


def _parse_int_loose(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v:
        return int(round(v))
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_float_loose(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v == v:
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _crossed_level(prev: float | None, cur: float | None, level: float) -> bool:
    if prev is None or cur is None:
        return False
    return (prev - level) * (cur - level) <= 0


def _angel_headers() -> dict[str, str]:
    return dict(
        api_key=settings.angel_api_key.strip(),
        jwt_token=settings.angel_jwt_token.strip(),
        source_id=(settings.angel_source_id or "WEB").strip(),
        client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
        client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
        mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
        user_type=(settings.angel_user_type or "USER").strip(),
    )


def _parse_order_book_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get("orderBook"), list):
        return [x for x in data["orderBook"] if isinstance(x, dict)]
    return []


def _order_row_for_id(rows: list[dict[str, Any]], order_id: str) -> dict[str, Any] | None:
    oid = (order_id or "").strip()
    if not oid:
        return None
    for r in rows:
        rid = str(r.get("orderid") or r.get("orderId") or "").strip()
        if rid == oid:
            return r
    return None


def _synthetic_option_mark(pos: TradePosition, index_ltp: float) -> float:
    u0 = pos.underlying_at_entry
    if u0 is None:
        u0 = index_ltp
    du = index_ltp - float(u0)
    mult = -0.35 if (pos.side or "").upper() == "PUT" else 0.35
    ep = float(pos.entry_price or 0.0)
    if ep <= 0:
        ep = max(5.0, abs(du) * 0.05)
    m = ep + du * mult
    return max(0.05, m)


def _poll_live_entry_fill(db: Session, pos: TradePosition) -> None:
    if not pos.order_id:
        return
    try:
        raw = angel_orders.get_order_book(
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0), **_angel_headers()
        )
    except RuntimeError as e:
        tr.update_position_fields(db, pos, last_order_message=str(e)[:500])
        return
    rows = _parse_order_book_list(raw)
    row = _order_row_for_id(rows, pos.order_id)
    if not row:
        return
    status = str(row.get("orderstatus") or row.get("orderStatus") or "").strip().lower()
    text = str(row.get("text") or row.get("rejectReason") or "")
    try:
        avg = float(row.get("averageprice") or row.get("filledshares") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    if status in ("rejected", "cancelled"):
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode=pos.trading_mode,
            leg=pos.leg_id,
            action="ORDER_REJECTED" if "reject" in status or status == "rejected" else "ORDER_CANCELLED",
            symbol=pos.trading_symbol,
            strike=pos.strike,
            quantity=pos.quantity,
            order_id=pos.order_id,
            message=text or status,
        )
        pos.status = "CLOSED"
        pos.exit_reason = "ORDER_REJECTED" if "reject" in status or status == "rejected" else "ORDER_CANCELLED"
        pos.exit_time = datetime.now(timezone.utc)
        pos.exit_price = 0.0
        pos.pnl = 0.0
        pos.last_order_message = (text or status)[:500]
        db.add(pos)
        db.commit()
        return
    if status in ("complete", "filled") and avg > 0:
        pos.entry_price = avg
        pos.last_order_message = (text or "FILLED")[:500]
        db.add(pos)
        db.commit()
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode=pos.trading_mode,
            leg=pos.leg_id,
            action="ORDER_FILLED",
            symbol=pos.trading_symbol,
            strike=pos.strike,
            quantity=pos.quantity,
            entry_price=avg,
            status="FILLED",
            order_id=pos.order_id,
            message=text or "Order filled",
        )


def _lot_multiplier(cfg: dict[str, Any]) -> int:
    v = _parse_int_loose(cfg.get("exchangeLotSize"))
    if v and v > 0:
        return v
    return max(1, int(settings.default_sensex_option_lot_size or 20))


def _in_trading_window(now: datetime, start_s: str, end_s: str) -> bool:
    st = _parse_hhmm(start_s) or dt_time(9, 15)
    et = _parse_hhmm(end_s) or dt_time(15, 30)
    cur = now.time()
    c = datetime(2000, 1, 1, cur.hour, cur.minute, cur.second).time()
    a = datetime(2000, 1, 1, st.hour, st.minute, st.second).time()
    b = datetime(2000, 1, 1, et.hour, et.minute, et.second).time()
    if a <= b:
        return a <= c <= b
    return c >= a or c <= b


def _past_or_at_session_end(now: datetime, end_s: str) -> bool:
    et = _parse_hhmm(end_s) or dt_time(15, 30)
    cur = now.time()
    return cur >= et


def _base_from_cfg(cfg: dict[str, Any]) -> float | None:
    for k in ("referenceClose", "sensexBasePrice", "basePrice"):
        x = _parse_float_loose(cfg.get(k))
        if x is not None and x >= 1000:
            return float(x)
    return None


def _row_ce_entry(base: float, gap: float, add: float, i: int) -> float:
    return float(base) + float(gap) - float(add) * float(i)


def _row_pe_entry(base: float, gap: float, add: float, i: int) -> float:
    return float(base) - float(gap) + float(add) * float(i)


def _parse_float_list(cfg: dict[str, Any], key: str) -> list[float] | None:
    v = cfg.get(key)
    if not isinstance(v, list) or not v:
        return None
    out: list[float] = []
    for x in v:
        f = _parse_float_loose(x)
        if f is None:
            return None
        out.append(float(f))
    return out


def _targets_ce_row(
    cfg: dict[str, Any],
    idx: int,
    base: float,
    gap: float,
    add: float,
    t1_pts: float,
    t2_pts: float,
) -> tuple[float, float]:
    lo = _parse_float_list(cfg, "sensexCeT1")
    l2 = _parse_float_list(cfg, "sensexCeT2")
    if lo and l2 and 0 <= idx < len(lo) and idx < len(l2):
        return float(lo[idx]), float(l2[idx])
    ent = _row_ce_entry(base, gap, add, idx)
    return ent + float(t1_pts), ent + float(t2_pts)


def _targets_pe_row(
    cfg: dict[str, Any],
    idx: int,
    base: float,
    gap: float,
    add: float,
    t1_pts: float,
    t2_pts: float,
) -> tuple[float, float]:
    lo = _parse_float_list(cfg, "sensexPeT1")
    l2 = _parse_float_list(cfg, "sensexPeT2")
    if lo and l2 and 0 <= idx < len(lo) and idx < len(l2):
        return float(lo[idx]), float(l2[idx])
    ent = _row_pe_entry(base, gap, add, idx)
    return ent - float(t1_pts), ent - float(t2_pts)


def _sensex_sl_for_side(cfg: dict[str, Any], base: float, side: str) -> float:
    if (side or "").upper() == "CALL":
        x = _parse_float_loose(cfg.get("sensexCeStopLoss"))
    else:
        x = _parse_float_loose(cfg.get("sensexPeStopLoss"))
    if x is not None and float(x) >= 1000.0:
        return float(x)
    return float(base)


def _sync_sob_targets_from_cfg(
    db: Session, pos: TradePosition, cfg: dict[str, Any], max_lots: int
) -> None:
    if not _sob_is_sensex_pos(pos):
        return
    base = _base_from_cfg(cfg)
    if base is None:
        return
    gap = float(_parse_float_loose(cfg.get("gap")) or 200.0)
    avg_step = float(_parse_float_loose(cfg.get("offset")) or 50.0)
    t1_pts = float(_parse_float_loose(cfg.get("target1Points")) or 80.0)
    t2_pts = float(_parse_float_loose(cfg.get("target2Points")) or 150.0)
    mx = max(1, int(max_lots))
    idx = min(max(0, int(pos.lots) - 1), mx - 1)
    su = (pos.side or "").upper()
    if su == "CALL":
        t1, t2 = _targets_ce_row(cfg, idx, float(base), gap, avg_step, t1_pts, t2_pts)
    else:
        t1, t2 = _targets_pe_row(cfg, idx, float(base), gap, avg_step, t1_pts, t2_pts)
    t1_done = str(pos.sl_mode or "") == "sensex_t1_done"
    if t1_done:
        tr.update_position_fields(db, pos, tp=float(t2))
    else:
        tr.update_position_fields(
            db,
            pos,
            put_sl_pts=int(round(t1)),
            tp=float(t2),
            sl_mode="sensex",
        )


def _index_option_strike(index_level: float) -> float:
    return round(float(index_level) / 100.0) * 100.0


def _ce_next_add_level(first_entry: float, lots: int, avg_step: float, base: float) -> float | None:
    nxt = first_entry - float(avg_step) * float(lots)
    if nxt <= base + float(avg_step):
        return None
    return nxt


def _pe_next_add_level(first_entry: float, lots: int, avg_step: float, base: float) -> float | None:
    nxt = first_entry + float(avg_step) * float(lots)
    if nxt >= base - float(avg_step):
        return None
    return nxt


def _sob_is_sensex_pos(pos: TradePosition) -> bool:
    return (pos.leg_id or "").upper() == LEG_SOB and str(pos.sl_mode or "").startswith("sensex")


def _close_sob(db: Session, pos: TradePosition, reason: str, index_ltp: float) -> None:
    mark = _synthetic_option_mark(pos, index_ltp)
    entry = float(pos.entry_price or 0.0)
    qty = int(pos.quantity)
    if entry <= 0:
        pnl = 0.0
        mark = 0.0
    else:
        pnl = (mark - entry) * qty
    tr.close_position(db, pos, exit_price=mark, exit_reason=reason[:64], pnl=pnl)
    tr.append_trading_log(
        db,
        user_id=pos.user_id,
        mode=pos.trading_mode,
        leg=LEG_SOB,
        action=reason[:32],
        symbol=pos.trading_symbol,
        strike=pos.strike,
        quantity=qty,
        entry_price=entry,
        exit_price=mark,
        pnl=pnl,
        status=reason[:32],
        order_id=pos.order_id,
        message=reason[:900],
    )


def _poll_live_add_fill(db: Session, pos: TradePosition, cfg: dict[str, Any]) -> None:
    u = (pos.unique_order_id or "").strip()
    if not u.upper().startswith("ADD:"):
        return
    pending_oid = u.split(":", 1)[-1].strip()
    if not pending_oid:
        return
    try:
        raw = angel_orders.get_order_book(
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0), **_angel_headers()
        )
    except RuntimeError as e:
        tr.update_position_fields(db, pos, last_order_message=str(e)[:500])
        return
    rows = _parse_order_book_list(raw)
    row = _order_row_for_id(rows, pending_oid)
    if not row:
        return
    status = str(row.get("orderstatus") or row.get("orderStatus") or "").strip().lower()
    try:
        avg = float(row.get("averageprice") or row.get("filledshares") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    if status in ("complete", "filled") and avg > 0:
        old_lots = max(1, int(pos.lots))
        old_qty = int(pos.quantity)
        old_ep = float(pos.entry_price or 0.0)
        per = old_qty // old_lots
        if per <= 0:
            per = max(1, _lot_multiplier({}))
        add_qty = per
        new_lots = old_lots + 1
        new_qty = old_qty + add_qty
        new_ep = (old_ep * old_qty + avg * add_qty) / max(1, new_qty)
        tr.update_position_fields(
            db,
            pos,
            lots=new_lots,
            quantity=new_qty,
            entry_price=new_ep,
            unique_order_id=None,
            last_order_message=f"ADD_FILLED lots={new_lots}",
        )
        mx = max(1, _parse_int_loose(cfg.get("tradeCount")) or 3)
        _sync_sob_targets_from_cfg(db, pos, cfg, mx)
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode=pos.trading_mode,
            leg=LEG_SOB,
            action="LOT_ADDED",
            symbol=pos.trading_symbol,
            strike=pos.strike,
            quantity=add_qty,
            entry_price=avg,
            status="FILLED",
            order_id=pending_oid,
            message=f"SENSEX add lot; total lots={new_lots}",
        )


def _place_sob_buy(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    *,
    side: str,
    index_ltp: float,
    option_strike: float,
    lots: int,
    range_level_base: float,
    first_entry_index: float,
    t1_index: float,
    t2_index: float,
) -> None:
    uid = st_row.user_id
    mode = (st_row.trading_mode or "PAPER").upper()
    su = "PUT" if side.upper() == "PUT" else "CALL"
    opt_side = "PE" if su == "PUT" else "CE"
    lot_mult = _lot_multiplier(cfg)
    lots_per = max(1, _parse_int_loose(cfg.get("lotsPerEntry")) or 1)
    qty = max(1, lots) * lot_mult * lots_per
    exch = (settings.angel_option_exchange or "BFO").upper()
    product = (settings.angel_option_product_type or "CARRYFORWARD").upper()
    off = float(cfg.get("offset") or 500)
    syn_entry = max(5.0, min(5000.0, off * 0.1))

    if mode == "LIVE":
        resolved = resolve_bfo_option(option_strike, opt_side)
        if resolved is None:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ERROR",
                symbol=None,
                strike=option_strike,
                quantity=qty,
                message="LIVE SENSEX: no BFO instrument mapping",
            )
            return
        qty = max(1, int(resolved.lotsize)) * lots_per
        try:
            raw = angel_orders.place_market_order(
                exchange=exch,
                tradingsymbol=resolved.tradingsymbol,
                symboltoken=resolved.token,
                transaction_type="BUY",
                quantity=qty,
                product_type=product,
                timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
                **_angel_headers(),
            )
        except RuntimeError as e:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                symbol=None,
                strike=option_strike,
                quantity=qty,
                message=str(e)[:900],
            )
            return
        data = raw.get("data") if isinstance(raw, dict) else None
        oid = ""
        if isinstance(data, dict):
            oid = str(data.get("orderid") or data.get("orderId") or "")
        msg = str(raw.get("message") or raw.get("Message") or "")
        if not oid:
            tr.append_trading_log(
                db,
                user_id=uid,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                message=msg or json.dumps(raw)[:900],
            )
            return
        pos = TradePosition(
            user_id=uid,
            leg_id=LEG_SOB,
            trading_mode="LIVE",
            side=su,
            range_level=float(range_level_base),
            strike=float(first_entry_index),
            tp=float(t2_index),
            lots=max(1, lots),
            quantity=qty,
            put_sl_pts=int(round(t1_index)),
            call_sl_pts=None,
            sl_mode="sensex",
            underlying_at_entry=index_ltp,
            entry_price=0.0,
            exchange=exch,
            trading_symbol=resolved.tradingsymbol,
            symbol_token=str(resolved.token),
            order_id=oid,
            unique_order_id=None,
            last_order_message=(msg or "PLACED")[:500],
        )
        tr.create_open_position(db, pos)
        tr.append_trading_log(
            db,
            user_id=uid,
            mode="LIVE",
            leg=LEG_SOB,
            action="LEVEL_TRIGGERED",
            symbol=resolved.tradingsymbol,
            strike=resolved.strike,
            quantity=qty,
            message=f"SENSEX {su} entry index≈{first_entry_index:g}; BASE={range_level_base:g}",
        )
        return

    pos = TradePosition(
        user_id=uid,
        leg_id=LEG_SOB,
        trading_mode="PAPER",
        side=su,
        range_level=float(range_level_base),
        strike=float(first_entry_index),
        tp=float(t2_index),
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
        message=f"SENSEX {su} BASE={range_level_base:g} trigger={first_entry_index:g} T1={t1_index:g} T2={t2_index:g}",
    )


def _place_sob_add_lot(db: Session, pos: TradePosition, cfg: dict[str, Any], index_ltp: float) -> None:
    mode = (pos.trading_mode or "PAPER").upper()
    opt_side = "PE" if (pos.side or "").upper() == "PUT" else "CE"
    option_strike = _index_option_strike(float(pos.strike))
    lot_mult = _lot_multiplier(cfg)
    lots_per = max(1, _parse_int_loose(cfg.get("lotsPerEntry")) or 1)
    add_qty = lot_mult * lots_per
    exch = (settings.angel_option_exchange or "BFO").upper()
    product = (settings.angel_option_product_type or "CARRYFORWARD").upper()
    off = float(cfg.get("offset") or 500)
    syn_add = max(5.0, min(5000.0, off * 0.1))

    if mode == "LIVE":
        resolved = resolve_bfo_option(option_strike, opt_side)
        if resolved is None:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ERROR",
                message="SENSEX add: no BFO mapping",
            )
            return
        add_qty = max(1, int(resolved.lotsize)) * lots_per
        try:
            raw = angel_orders.place_market_order(
                exchange=exch,
                tradingsymbol=resolved.tradingsymbol,
                symboltoken=resolved.token,
                transaction_type="BUY",
                quantity=add_qty,
                product_type=product,
                timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
                **_angel_headers(),
            )
        except RuntimeError as e:
            tr.append_trading_log(
                db,
                user_id=pos.user_id,
                mode="LIVE",
                leg=LEG_SOB,
                action="ORDER_REJECTED",
                message=str(e)[:900],
            )
            return
        data = raw.get("data") if isinstance(raw, dict) else None
        oid = ""
        if isinstance(data, dict):
            oid = str(data.get("orderid") or data.get("orderId") or "")
        if not oid:
            return
        tr.update_position_fields(
            db,
            pos,
            unique_order_id=f"ADD:{oid}",
            last_order_message="ADD_PENDING",
        )
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode="LIVE",
            leg=LEG_SOB,
            action="LEVEL_TRIGGERED",
            symbol=resolved.tradingsymbol,
            quantity=add_qty,
            order_id=oid,
            message="SENSEX add lot order placed",
        )
        return

    old_lots = max(1, int(pos.lots))
    old_qty = int(pos.quantity)
    old_ep = float(pos.entry_price or 0.0)
    new_lots = old_lots + 1
    new_qty = old_qty + add_qty
    new_ep = (old_ep * old_qty + syn_add * add_qty) / max(1, new_qty)
    tr.update_position_fields(db, pos, lots=new_lots, quantity=new_qty, entry_price=new_ep)
    mx = max(1, _parse_int_loose(cfg.get("tradeCount")) or 3)
    _sync_sob_targets_from_cfg(db, pos, cfg, mx)
    tr.append_trading_log(
        db,
        user_id=pos.user_id,
        mode="PAPER",
        leg=LEG_SOB,
        action="LOT_ADDED",
        symbol=pos.trading_symbol,
        quantity=add_qty,
        entry_price=syn_add,
        message=f"SENSEX add lot; lots={new_lots}",
    )


def _total_lots(cfg: dict[str, Any]) -> int:
    lpe = max(1, _parse_int_loose(cfg.get("lotsPerEntry")) or 6)
    tc = max(1, _parse_int_loose(cfg.get("tradeCount")) or 1)
    return max(1, lpe * tc)


def _tp1_exit_lots(cfg: dict[str, Any], total: int) -> int:
    t1 = _parse_int_loose(cfg.get("tp1ExitLots"))
    if t1 is not None and t1 > 0:
        return max(1, min(total - 1, int(t1)))
    pct = float(cfg.get("partialClosePercent") or 50)
    pct = max(1.0, min(99.0, pct))
    return max(1, min(total - 1, int(round(total * pct / 100.0))))


def _tp2_exit_lots(cfg: dict[str, Any], total: int) -> int:
    t2 = _parse_int_loose(cfg.get("tp2ExitLots"))
    if t2 is not None and t2 > 0:
        return max(1, int(t2))
    return max(1, total - _tp1_exit_lots(cfg, total))


def _adaptive_retrace_high_call(cfg: dict[str, Any]) -> float:
    v = _parse_float_loose(cfg.get("adaptiveCallRetraceHigh"))
    if v is not None and 0 < v < 500:
        return float(v)
    return 100.0


def _adaptive_retrace_high_put(cfg: dict[str, Any]) -> float:
    v = _parse_float_loose(cfg.get("adaptivePutRetraceHigh"))
    if v is not None and 0 < v < 500:
        return float(v)
    return 190.0


def _adaptive_retrace_low_put(cfg: dict[str, Any]) -> float:
    v = _parse_float_loose(cfg.get("adaptivePutRetraceLow"))
    if v is not None and 0 < v < 500:
        return float(v)
    return 100.0


def _adaptive_retrace_low_call(cfg: dict[str, Any]) -> float:
    v = _parse_float_loose(cfg.get("adaptiveCallRetraceLow"))
    if v is not None and 0 < v < 500:
        return float(v)
    return 190.0


def _opposite_trigger_sl(base: float, gap: float, side: str) -> float:
    """Call SL = lower trigger; Put SL = upper trigger (spot-based per spec)."""
    if (side or "").upper() == "CALL":
        return float(base) - float(gap)
    return float(base) + float(gap)


def _persist_runtime(db: Session, user_id: int, runtime: dict[str, Any]) -> None:
    tr.merge_strategy_runtime(db, user_id, runtime)


def _seed_adaptive_high(runtime: dict[str, Any], index_ltp: float) -> None:
    runtime["track_adaptive_high"] = True
    runtime["adaptive_high"] = float(index_ltp)


def _seed_adaptive_low(runtime: dict[str, Any], index_ltp: float) -> None:
    runtime["track_adaptive_low"] = True
    runtime["adaptive_low"] = float(index_ltp)


def _update_adaptive_extremes(runtime: dict[str, Any], index_ltp: float) -> None:
    if runtime.get("track_adaptive_high"):
        cur = float(runtime.get("adaptive_high") or index_ltp)
        runtime["adaptive_high"] = max(cur, float(index_ltp))
    if runtime.get("track_adaptive_low"):
        cur = float(runtime.get("adaptive_low") or index_ltp)
        runtime["adaptive_low"] = min(cur, float(index_ltp))


def _paper_add_lots(
    db: Session, pos: TradePosition, cfg: dict[str, Any], add_lots: int, index_ltp: float
) -> None:
    add_lots = max(1, int(add_lots))
    old_lots = max(1, int(pos.lots))
    old_qty = int(pos.quantity)
    per = max(1, old_qty // old_lots)
    add_qty = per * add_lots
    old_ep = float(pos.entry_price or 0.0)
    syn_add = max(5.0, min(5000.0, float(cfg.get("offset") or 50) * 0.1))
    new_lots = old_lots + add_lots
    new_qty = old_qty + add_qty
    new_ep = (old_ep * old_qty + syn_add * add_qty) / max(1, new_qty) if old_ep > 0 else syn_add
    tr.update_position_fields(db, pos, lots=new_lots, quantity=new_qty, entry_price=new_ep)
    tr.append_trading_log(
        db,
        user_id=pos.user_id,
        mode=pos.trading_mode,
        leg=LEG_SOB,
        action="TP1_REFILL",
        symbol=pos.trading_symbol,
        quantity=add_qty,
        message=f"Refill {add_lots} lot(s); total lots={new_lots}",
    )


def _maybe_exit_t2(
    db: Session,
    pos: TradePosition,
    index_ltp: float,
    prev: float | None,
    *,
    user_id: int,
    runtime: dict[str, Any],
    side: str,
) -> bool:
    t2 = float(pos.tp) if pos.tp is not None else None
    if t2 is None or prev is None:
        return False
    if not _crossed_level(prev, index_ltp, t2):
        return False
    _close_sob(db, pos, "TP_HIT", index_ltp)
    if (side or "").upper() == "CALL":
        runtime["flat_mode"] = "CALL_TP2_DONE"
        runtime["last_call_entry"] = float(pos.strike)
        runtime["last_call_tp1"] = float(pos.put_sl_pts or 0)
        runtime["last_call_tp2"] = float(t2)
        _seed_adaptive_high(runtime, index_ltp)
    else:
        runtime["flat_mode"] = "PUT_TP2_DONE"
        runtime["last_put_entry"] = float(pos.strike)
        runtime["last_put_tp1"] = float(pos.put_sl_pts or 0)
        runtime["last_put_tp2"] = float(t2)
        _seed_adaptive_low(runtime, index_ltp)
    _persist_runtime(db, user_id, runtime)
    return True


def _maybe_partial_t1(
    db: Session, pos: TradePosition, index_ltp: float, prev: float | None, cfg: dict[str, Any]
) -> None:
    if (pos.trading_mode or "").upper() == "LIVE":
        return
    if str(pos.sl_mode or "") == "sensex_t1_done":
        return
    if prev is None:
        return
    t1 = float(pos.put_sl_pts) if pos.put_sl_pts is not None else None
    if t1 is None or pos.tp is None:
        return
    if not _crossed_level(prev, index_ltp, t1):
        return

    total = _total_lots(cfg)
    close_lots = _tp1_exit_lots(cfg, total)
    lots = max(1, int(pos.lots))
    mark = _synthetic_option_mark(pos, index_ltp)
    entry = float(pos.entry_price or 0.0)
    qty = int(pos.quantity)

    if lots <= close_lots:
        tr.update_position_fields(db, pos, sl_mode="sensex_t1_done")
        tr.append_trading_log(
            db,
            user_id=pos.user_id,
            mode=pos.trading_mode,
            leg=LEG_SOB,
            action="T1_PARTIAL",
            quantity=qty,
            entry_price=entry,
            exit_price=mark,
            pnl=(mark - entry) * qty if entry > 0 else 0.0,
            message="SENSEX T1: mark TP1 (exit at T2 or SL)",
        )
        return

    per = max(1, qty // lots)
    closed_qty = per * close_lots
    rem_lots = lots - close_lots
    rem_qty = per * rem_lots
    pnl_part = (mark - entry) * closed_qty if entry > 0 else 0.0
    tr.update_position_fields(
        db,
        pos,
        lots=rem_lots,
        quantity=rem_qty,
        sl_mode="sensex_t1_done",
    )
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
        message=f"SENSEX T1 partial closed {close_lots} lot(s); remaining {rem_lots}",
    )


def _maybe_tp1_refill(
    db: Session,
    pos: TradePosition,
    cfg: dict[str, Any],
    index_ltp: float,
    prev: float | None,
    entry_level: float,
) -> None:
    if (pos.trading_mode or "").upper() == "LIVE":
        return
    if str(pos.sl_mode or "") != "sensex_t1_done":
        return
    if prev is None:
        return
    total = _total_lots(cfg)
    refill = _tp1_exit_lots(cfg, total)
    if int(pos.lots) >= total:
        return
    if not _crossed_level(prev, index_ltp, float(entry_level)):
        return
    _paper_add_lots(db, pos, cfg, refill, index_ltp)


def tick_sensex_option_buy_session(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    index_ltp: float,
    prev: float | None,
) -> None:
    """High/Low re-entry system per user specification."""
    uid = st_row.user_id
    now = _now_ist()
    start_s = str(cfg.get("startTime") or "09:15")
    end_s = str(cfg.get("endTime") or "15:30")
    in_win = _in_trading_window(now, start_s, end_s)
    base = _base_from_cfg(cfg)
    gap = float(_parse_float_loose(cfg.get("gap")) or 200.0)
    avg_step = float(_parse_float_loose(cfg.get("offset")) or 50.0)
    t1_pts = float(_parse_float_loose(cfg.get("target1Points")) or 80.0)
    t2_pts = float(_parse_float_loose(cfg.get("target2Points")) or 150.0)
    first_entry = bool(cfg.get("firstEntryEnabled", True))
    total_lots = _total_lots(cfg)
    tp2_lots = _tp2_exit_lots(cfg, total_lots)

    if gap <= 0 or base is None:
        return

    upper_trig = float(base) + gap
    lower_trig = float(base) - gap
    runtime = tr.load_strategy_runtime(cfg)

    _update_adaptive_extremes(runtime, index_ltp)

    sl_mode = str(cfg.get("slMode") or "auto")
    pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)
    if pos and pos.trading_mode == "LIVE" and float(pos.entry_price or 0) <= 0 and pos.order_id:
        _poll_live_entry_fill(db, pos)

    pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)

    if sl_mode == "auto" and _past_or_at_session_end(now, end_s):
        while True:
            p2 = tr.get_open_position_by_leg(db, uid, LEG_SOB)
            if p2 is None:
                break
            if p2.trading_mode == "LIVE" and float(p2.entry_price or 0) <= 0 and p2.order_id:
                try:
                    angel_orders.cancel_order(
                        variety="NORMAL",
                        order_id=str(p2.order_id),
                        timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
                        **_angel_headers(),
                    )
                except RuntimeError:
                    pass
            _close_sob(db, p2, "AUTO_EXIT", index_ltp)
        runtime = {
            "track_adaptive_high": False,
            "track_adaptive_low": False,
            "adaptive_high": None,
            "adaptive_low": None,
            "flat_mode": None,
        }
        _persist_runtime(db, uid, runtime)
        return

    if pos and _sob_is_sensex_pos(pos):
        if pos.trading_mode == "LIVE" and float(pos.entry_price or 0) <= 0:
            _persist_runtime(db, uid, runtime)
            return

        su = (pos.side or "CALL").upper()
        entry_level = float(pos.strike)
        sl_px = _opposite_trigger_sl(float(base), gap, su)

        if prev is not None and _crossed_level(prev, index_ltp, sl_px):
            _close_sob(db, pos, "CALL_SL_HIT" if su == "CALL" else "PUT_SL_HIT", index_ltp)
            opp = "PUT" if su == "CALL" else "CALL"
            trig = lower_trig if opp == "PUT" else upper_trig
            if opp == "CALL":
                t1, t2 = trig + t1_pts, trig + t2_pts
            else:
                t1, t2 = trig - t1_pts, trig - t2_pts
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side=opp,
                index_ltp=index_ltp,
                option_strike=_index_option_strike(trig),
                lots=total_lots,
                range_level_base=float(base),
                first_entry_index=trig,
                t1_index=t1,
                t2_index=t2,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

        if _maybe_exit_t2(db, pos, index_ltp, prev, user_id=uid, runtime=runtime, side=su):
            _persist_runtime(db, uid, runtime)
            return

        _maybe_partial_t1(db, pos, index_ltp, prev, cfg)
        _maybe_tp1_refill(db, pos, cfg, index_ltp, prev, entry_level)
        _persist_runtime(db, uid, runtime)
        return

    _persist_runtime(db, uid, runtime)

    if prev is None:
        return

    mode_u = (st_row.trading_mode or "PAPER").upper()
    if mode_u != "PAPER" and not in_win:
        return

    if tr.get_open_position_by_leg(db, uid, LEG_SOB):
        return

    flat_mode = runtime.get("flat_mode")

    # TP2 pullback re-entry at TP1 level (3 lots)
    if flat_mode == "CALL_TP2_DONE":
        tp1_level = float(runtime.get("last_call_tp1") or 0)
        t2_level = float(runtime.get("last_call_tp2") or 0)
        if tp1_level > 0 and _crossed_level(prev, index_ltp, tp1_level):
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side="CALL",
                index_ltp=index_ltp,
                option_strike=_index_option_strike(tp1_level),
                lots=tp2_lots,
                range_level_base=float(base),
                first_entry_index=tp1_level,
                t1_index=tp1_level,
                t2_index=t2_level,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

    if flat_mode == "PUT_TP2_DONE":
        tp1_level = float(runtime.get("last_put_tp1") or 0)
        t2_level = float(runtime.get("last_put_tp2") or 0)
        if tp1_level > 0 and _crossed_level(prev, index_ltp, tp1_level):
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side="PUT",
                index_ltp=index_ltp,
                option_strike=_index_option_strike(tp1_level),
                lots=tp2_lots,
                range_level_base=float(base),
                first_entry_index=tp1_level,
                t1_index=tp1_level,
                t2_index=t2_level,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

    # Adaptive entries — only after call/put TP2 completion tracking is active
    if runtime.get("track_adaptive_high"):
        ah = float(runtime.get("adaptive_high") or index_ltp)
        call_retrace = _adaptive_retrace_high_call(cfg)
        put_retrace = _adaptive_retrace_high_put(cfg)
        call_trig = ah - call_retrace
        put_trig = ah - put_retrace

        if _crossed_level(prev, index_ltp, call_trig):
            t1, t2 = call_trig + t1_pts, call_trig + t2_pts
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side="CALL",
                index_ltp=index_ltp,
                option_strike=_index_option_strike(call_trig),
                lots=total_lots,
                range_level_base=float(base),
                first_entry_index=call_trig,
                t1_index=t1,
                t2_index=t2,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

        if _crossed_level(prev, index_ltp, put_trig):
            t1, t2 = put_trig - t1_pts, put_trig - t2_pts
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side="PUT",
                index_ltp=index_ltp,
                option_strike=_index_option_strike(put_trig),
                lots=total_lots,
                range_level_base=float(base),
                first_entry_index=put_trig,
                t1_index=t1,
                t2_index=t2,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

    if runtime.get("track_adaptive_low"):
        al = float(runtime.get("adaptive_low") or index_ltp)
        put_retrace = _adaptive_retrace_low_put(cfg)
        call_retrace = _adaptive_retrace_low_call(cfg)
        put_trig = al + put_retrace
        call_trig = al + call_retrace

        if _crossed_level(prev, index_ltp, put_trig):
            t1, t2 = put_trig - t1_pts, put_trig - t2_pts
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side="PUT",
                index_ltp=index_ltp,
                option_strike=_index_option_strike(put_trig),
                lots=total_lots,
                range_level_base=float(base),
                first_entry_index=put_trig,
                t1_index=t1,
                t2_index=t2,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

        if _crossed_level(prev, index_ltp, call_trig):
            t1, t2 = call_trig + t1_pts, call_trig + t2_pts
            _place_sob_buy(
                db,
                st_row,
                cfg,
                side="CALL",
                index_ltp=index_ltp,
                option_strike=_index_option_strike(call_trig),
                lots=total_lots,
                range_level_base=float(base),
                first_entry_index=call_trig,
                t1_index=t1,
                t2_index=t2,
            )
            runtime["flat_mode"] = None
            _persist_runtime(db, uid, runtime)
            return

    # Initial range trigger (first entry)
    if not first_entry:
        return

    if tr.leg_has_session_blocking_exit_today_ist(db, uid, LEG_SOB) and str(
        cfg.get("legEntryMode") or "once"
    ).lower() != "multi":
        return

    ce_cross = _crossed_level(prev, index_ltp, upper_trig)
    pe_cross = _crossed_level(prev, index_ltp, lower_trig)

    side_to_open: str | None = None
    if ce_cross and not pe_cross:
        side_to_open = "CALL"
    elif pe_cross and not ce_cross:
        side_to_open = "PUT"
    elif ce_cross and pe_cross:
        side_to_open = "CALL" if float(index_ltp) >= float(base) else "PUT"

    if side_to_open == "CALL":
        t1, t2 = upper_trig + t1_pts, upper_trig + t2_pts
        _place_sob_buy(
            db,
            st_row,
            cfg,
            side="CALL",
            index_ltp=index_ltp,
            option_strike=_index_option_strike(upper_trig),
            lots=total_lots,
            range_level_base=float(base),
            first_entry_index=upper_trig,
            t1_index=t1,
            t2_index=t2,
        )
        runtime["last_call_entry"] = upper_trig
        runtime["last_call_tp1"] = t1
        runtime["last_call_tp2"] = t2
        _persist_runtime(db, uid, runtime)
        return

    if side_to_open == "PUT":
        t1, t2 = lower_trig - t1_pts, lower_trig - t2_pts
        _place_sob_buy(
            db,
            st_row,
            cfg,
            side="PUT",
            index_ltp=index_ltp,
            option_strike=_index_option_strike(lower_trig),
            lots=total_lots,
            range_level_base=float(base),
            first_entry_index=lower_trig,
            t1_index=t1,
            t2_index=t2,
        )
        runtime["last_put_entry"] = lower_trig
        runtime["last_put_tp1"] = t1
        runtime["last_put_tp2"] = t2
        _persist_runtime(db, uid, runtime)


