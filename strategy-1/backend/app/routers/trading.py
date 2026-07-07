"""Trading settings, logs, positions, and Angel order helpers (authenticated)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    ActivePositionOut,
    CompletedPositionOut,
    OrderCancelBody,
    OrderModifyBody,
    TradingLogOut,
    TradingSettingsOut,
    TradingSettingsPut,
)
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.market_ltp import get_index_ltp_cached
from app.services.sensex_trend_core import TrendParams, open_cycle_sl_level, tp1_level_for
from app.services.sensex_trend_core import EntryKind
from app.services.trading_engine import _angel_headers, _synthetic_option_mark, manual_close_leg

router = APIRouter(prefix="/trading", tags=["trading"])


def _active_position_levels(
    pos: Any,
    cfg: dict[str, Any],
    runtime: dict[str, Any],
) -> tuple[float | None, float | None, float | None, bool]:
    """Return (tp1_level, tp2_trail_level, sl_level, tp1_hit) for dashboard."""
    p = TrendParams.from_config(cfg)
    side = (pos.side or "CALL").upper()
    index_entry = float(pos.strike or 0)
    tp1_hit = str(pos.sl_mode or "") == "sensex_t1_done"

    t1_core = float(runtime.get("t1_level_core") or 0) or float(pos.put_sl_pts or 0)
    if t1_core <= 0 and index_entry > 0:
        pts = p.tp1_pts_initial if int(runtime.get("entries_filled") or 1) <= 1 else p.tp1_pts
        t1_core = tp1_level_for(side, index_entry, pts)

    sl_level = float(runtime.get("sl_level") or 0)
    if sl_level <= 0 and index_entry > 0:
        entry_kind = EntryKind.REENTRY if str(runtime.get("entry_kind") or "") == "REENTRY" else EntryKind.INITIAL
        adaptive_ref = float(runtime.get("adaptive_ref") or pos.range_level or index_entry)
        sl_level = open_cycle_sl_level(side, index_entry, p, entry_kind=entry_kind, adaptive_ref=adaptive_ref)

    tp2_trail: float | None = None
    trail_extreme = runtime.get("trail_extreme")
    if trail_extreme is not None and float(trail_extreme) > 0:
        extreme = float(trail_extreme)
        if side == "CALL":
            tp2_trail = round(extreme - p.tp2_trail, 2)
        else:
            tp2_trail = round(extreme + p.tp2_trail, 2)

    return (
        round(t1_core, 2) if t1_core > 0 else None,
        tp2_trail,
        round(sl_level, 2) if sl_level > 0 else None,
        tp1_hit,
    )


def _iso(dt: Any) -> str | None:
    """RFC 3339 UTC with Z for JSON (avoids JS interpreting naive strings as local time)."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        s = dt.isoformat(timespec="milliseconds")
        return s.replace("+00:00", "Z")
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.isoformat()
    if hasattr(dt, "isoformat"):
        return str(dt.isoformat())
    return str(dt)


@router.get("/settings", response_model=TradingSettingsOut)
def get_trading_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = tr.get_or_create_strategy_settings(db, user.id)
    cfg = tr.load_config_dict(db, user.id)
    return TradingSettingsOut(
        config=cfg,
        algo_running=bool(row.algo_running),
        trading_mode=(row.trading_mode or "PAPER").upper(),
    )


@router.put("/settings", response_model=TradingSettingsOut)
def put_trading_settings(
    body: TradingSettingsPut,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = tr.get_or_create_strategy_settings(db, user.id)
    prev_run = bool(row.algo_running)
    prev_mode = (row.trading_mode or "PAPER").upper()

    merged_config = None
    prev_leg_mode: str | None = None
    if body.config is not None:
        existing = tr.load_config_dict(db, user.id)
        prev_leg_mode = str(existing.get("legEntryMode") or "once").strip().lower()
        merged_config = {**existing, **body.config}

    tr.save_strategy_settings(
        db,
        user.id,
        config=merged_config,
        algo_running=body.algo_running,
        trading_mode=body.trading_mode,
    )
    row = tr.get_or_create_strategy_settings(db, user.id)
    new_run = bool(row.algo_running)
    new_mode = (row.trading_mode or "PAPER").upper()

    if body.algo_running is not None and new_run != prev_run:
        tr.append_trading_log(
            db,
            user_id=user.id,
            mode=new_mode,
            leg="-",
            action="ALGO_STARTED" if new_run else "ALGO_STOPPED",
            message="Algo enabled" if new_run else "Algo disabled",
        )
    if body.trading_mode is not None and new_mode != prev_mode:
        tr.append_trading_log(
            db,
            user_id=user.id,
            mode=new_mode,
            leg="-",
            action="MODE_CHANGED",
            message=f"Trading mode set to {new_mode}",
        )

    if merged_config is not None and prev_leg_mode is not None:
        nm = str(merged_config.get("legEntryMode") or "once").strip().lower()
        if nm != prev_leg_mode:
            tr.append_trading_log(
                db,
                user_id=user.id,
                mode=new_mode,
                leg="-",
                action="CONFIG_CHANGED",
                message=f"Leg entry mode: {nm}",
            )

    cfg = tr.load_config_dict(db, user.id)
    return TradingSettingsOut(config=cfg, algo_running=new_run, trading_mode=new_mode)


@router.get("/logs", response_model=list[TradingLogOut])
def list_logs(
    limit: int = 500,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = tr.list_trading_logs(db, user.id, limit=limit)
    out: list[TradingLogOut] = []
    for r in rows:
        out.append(
            TradingLogOut(
                id=r.id,
                created_at=_iso(r.created_at) or "",
                mode=r.mode,
                leg=r.leg,
                action=r.action,
                symbol=r.symbol,
                strike=r.strike,
                quantity=r.quantity,
                entry_price=r.entry_price,
                exit_price=r.exit_price,
                pnl=r.pnl,
                status=r.status,
                order_id=r.order_id,
                message=r.message,
            )
        )
    return out


@router.get("/positions/active", response_model=list[ActivePositionOut])
def list_active_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ltp, _, ok = get_index_ltp_cached()
    idx = float(ltp) if ok and ltp is not None else 0.0
    cfg = tr.load_config_dict(db, user.id)
    runtime = tr.load_strategy_runtime(cfg)
    rows = tr.list_open_positions(db, user.id)
    out: list[ActivePositionOut] = []
    for p in rows:
        st = "PENDING_FILL" if p.trading_mode == "LIVE" and float(p.entry_price or 0) <= 0 else "OPEN"
        msg = (p.last_order_message or "").strip()
        if st == "PENDING_FILL" and msg and "reject" in msg.lower():
            st = "REJECTED"
        mark = _synthetic_option_mark(p, idx) if idx > 0 else float(p.entry_price or 0)
        entry = float(p.entry_price or 0.0)
        qty = int(p.quantity)
        pnl = (mark - entry) * qty if entry > 0 else 0.0
        tp1, tp2_trail, sl_level, tp1_hit = _active_position_levels(p, cfg, runtime)
        out.append(
            ActivePositionOut(
                id=p.id,
                leg_id=p.leg_id,
                side=p.side,
                strike=float(p.strike),
                lots=int(p.lots),
                quantity=qty,
                entry_price=entry,
                current_price=mark,
                pnl=pnl,
                status=st,
                trading_mode=p.trading_mode,
                entry_time=_iso(p.entry_time),
                symbol=p.trading_symbol,
                index_entry=float(p.strike) if p.strike else None,
                tp1_level=tp1,
                tp2_trail_level=tp2_trail,
                sl_level=sl_level,
                tp1_hit=tp1_hit,
                order_id=p.order_id,
                last_order_message=msg or None,
            )
        )
    return out


@router.get("/positions/completed", response_model=list[CompletedPositionOut])
def list_completed_positions(
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = tr.list_completed_positions(db, user.id, limit=limit)
    return [
        CompletedPositionOut(
            id=r.id,
            entry_time=_iso(r.entry_time),
            exit_time=_iso(r.exit_time),
            leg_id=r.leg_id,
            side=r.side,
            range_level=r.range_level,
            strike=r.strike,
            tp=r.tp,
            symbol=r.trading_symbol,
            entry_price=r.entry_price,
            exit_price=r.exit_price,
            pnl=r.pnl,
            trading_mode=r.trading_mode,
            exit_reason=r.exit_reason,
            lots=int(r.lots) if r.lots else None,
        )
        for r in rows
    ]


@router.post("/reconcile")
def reconcile_trading(user: User = Depends(get_current_user)):
    """After reconnect: poll live fills and evaluate TP/SL with current index."""
    from app.services.trading_engine import tick_once

    tick_once()
    tick_once()
    return {"ok": True}


@router.delete("/positions/completed")
def clear_completed_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove all CLOSED positions for the current user (paper/live history)."""
    n = tr.delete_all_completed_positions(db, user.id)
    return {"ok": True, "deleted": n}


@router.delete("/logs")
def clear_trading_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove all trading log rows for the current user."""
    n = tr.delete_all_trading_logs(db, user.id)
    return {"ok": True, "deleted": n}


@router.post("/legs/{leg_id}/close")
def close_leg_manual(
    leg_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        manual_close_leg(db, user.id, leg_id)
    except ValueError as e:
        if str(e) == "NO_OPEN_POSITION":
            raise HTTPException(status_code=404, detail="No open position for this leg") from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/order/cancel")
def cancel_broker_order(body: OrderCancelBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(status_code=503, detail="Angel One not configured")
    try:
        raw = angel_orders.cancel_order(
            variety=body.variety.strip() or "NORMAL",
            order_id=body.order_id.strip(),
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
            **_angel_headers(),
        )
    except RuntimeError as e:
        tr.append_trading_log(
            db,
            user_id=user.id,
            mode="LIVE",
            leg="-",
            action="ERROR",
            order_id=body.order_id,
            message=f"Cancel failed: {e}"[:900],
        )
        raise HTTPException(status_code=502, detail=str(e)) from e
    tr.append_trading_log(
        db,
        user_id=user.id,
        mode="LIVE",
        leg="-",
        action="ORDER_CANCELLED",
        order_id=body.order_id,
        message=str(raw.get("message") or raw)[:900],
    )
    return {"ok": True, "raw": raw}


@router.post("/order/modify")
def modify_broker_order(body: OrderModifyBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(status_code=503, detail="Angel One not configured")
    try:
        raw = angel_orders.modify_order(
            variety=body.variety.strip() or "NORMAL",
            order_id=body.order_id.strip(),
            tradingsymbol=body.tradingsymbol.strip(),
            symboltoken=body.symboltoken.strip(),
            transaction_type=body.transaction_type,
            exchange=body.exchange.strip().upper(),
            order_type=body.order_type,
            product_type=body.product_type,
            duration=body.duration,
            quantity=int(body.quantity),
            price=body.price,
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
            **_angel_headers(),
        )
    except RuntimeError as e:
        tr.append_trading_log(
            db,
            user_id=user.id,
            mode="LIVE",
            leg="-",
            action="ERROR",
            order_id=body.order_id,
            message=f"Modify failed: {e}"[:900],
        )
        raise HTTPException(status_code=502, detail=str(e)) from e
    tr.append_trading_log(
        db,
        user_id=user.id,
        mode="LIVE",
        leg="-",
        action="ORDER_MODIFIED",
        order_id=body.order_id,
        message=str(raw.get("message") or "modified")[:900],
    )
    return {"ok": True, "raw": raw}


@router.get("/order/status")
def order_status(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del db
    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(status_code=503, detail="Angel One not configured")
    try:
        raw = angel_orders.get_order_book(
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0), **_angel_headers()
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    data = raw.get("data")
    rows = data if isinstance(data, list) else []
    oid = order_id.strip()
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("orderid") or r.get("orderId") or "").strip()
        if rid == oid:
            return {"ok": True, "order": r, "user": user.id}
    return {"ok": False, "message": "Order not found in book", "user": user.id}


@router.post("/backtest")
def run_strategy_backtest(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Run SENSEX Adaptive Trend backtest using the same core engine as live trading.
    Body: { from_date, to_date, config?: dict, initial_capital?: number }
    """
    from_date = str(body.get("from_date") or "").strip()
    to_date = str(body.get("to_date") or from_date).strip()
    if not from_date:
        raise HTTPException(status_code=422, detail="from_date required (YYYY-MM-DD)")

    cfg = body.get("config") if isinstance(body.get("config"), dict) else tr.load_config_dict(db, user.id)
    start = str(cfg.get("startTime") or "09:15")
    end = str(cfg.get("endTime") or "15:30")
    interval = str(body.get("interval") or "1")

    from app.routers.angel import angel_historical_candles_batch
    from app.services.sensex_trend_backtest import run_range_backtest

    batch = angel_historical_candles_batch(
        from_date=from_date,
        to_date=to_date,
        start=start,
        end=end,
        interval=interval,
        _user=user,
    )
    days_in: list[dict[str, Any]] = []
    for day in batch.get("days") or []:
        if not isinstance(day, dict):
            continue
        candles = day.get("candles") if isinstance(day.get("candles"), list) else []
        days_in.append({"date": day.get("date"), "candles": candles})

    initial_capital = float(body.get("initial_capital") or 0)
    result = run_range_backtest(days=days_in, cfg=cfg, initial_capital=initial_capital)
    result["from_date"] = from_date
    result["to_date"] = to_date
    result["days_count"] = len(days_in)
    return result
