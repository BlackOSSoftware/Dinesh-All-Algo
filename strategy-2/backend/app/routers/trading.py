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
    DashboardOut,
    GridBacktestOut,
    GridBacktestRunIn,
    GridLevelOut,
    MarketQuoteOut,
    OrderCancelBody,
    OrderModifyBody,
    TradingLogOut,
    TradingSettingsOut,
    TradingSettingsPut,
)
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.grid_logic import (
    build_grid_levels,
    compute_level_statuses,
    load_runtime,
    parse_strategy_config,
)
from app.services.grid_backtest import run_grid_backtest
from app.services.mcx_quotes import fetch_all_mcx_quotes, get_quote_by_key, quote_from_results
from app.services.trading_engine import _angel_headers, manual_close_leg

router = APIRouter(prefix="/trading", tags=["trading"])


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
        if new_run:
            parsed = parse_strategy_config(tr.load_config_dict(db, user.id))
            quote = get_quote_by_key(parsed["market"])
            px = float(quote.price if quote and quote.price > 0 else 0)
            tr.reset_algo_session(db, user.id, current_price=px)
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


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = tr.get_or_create_strategy_settings(db, user.id)
    cfg = tr.load_config_dict(db, user.id)
    parsed = parse_strategy_config(cfg)
    runtime = load_runtime(cfg)

    quotes_raw = fetch_all_mcx_quotes()
    quotes = [
        MarketQuoteOut(
            key=q.key,
            label=q.label,
            price=q.price,
            market_open=q.market_open,
            source=q.source,
            tradingsymbol=q.tradingsymbol,
            price_type=getattr(q, "price_type", "LTP"),
            error=q.error,
        )
        for q in quotes_raw
    ]

    selected = quote_from_results(quotes_raw, parsed["market"])
    current_price = float(selected.price if selected and selected.price > 0 else runtime.get("lastPrice") or 0)

    levels = build_grid_levels(
        reference_price=parsed["reference_price"],
        grid_gap=parsed["grid_gap"],
        levels_above=parsed["grid_levels_above"],
        levels_below=parsed["grid_levels_below"],
        initial_lots=parsed["initial_lots"],
        lots_per_grid=parsed["lots_per_grid"],
        invert_grid=parsed["invert_grid"],
    )
    grid_rows = compute_level_statuses(
        levels, runtime, current_price, invert_grid=parsed["invert_grid"]
    )
    grid_levels = [
        GridLevelOut(level=r["level"], price=r["price"], action=r["action"], status=r["status"])
        for r in grid_rows
    ]

    position_lots = int(runtime.get("positionLots") or 0)
    avg_entry = float(runtime.get("avgEntryPrice") or 0)
    unrealized = (current_price - avg_entry) * position_lots if position_lots > 0 and current_price > 0 else 0.0

    active_rows = tr.list_open_positions(db, user.id)
    active_trades: list[ActivePositionOut] = []
    for p in active_rows:
        mark = current_price if current_price > 0 else float(p.entry_price or 0)
        entry = float(p.entry_price or 0.0)
        qty = int(p.quantity)
        pnl = (mark - entry) * qty if entry > 0 else 0.0
        active_trades.append(
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
                status="OPEN",
                trading_mode=p.trading_mode,
                entry_time=_iso(p.entry_time),
            )
        )

    completed_rows = tr.list_completed_positions(db, user.id, limit=100)
    completed_trades = [
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
        )
        for r in completed_rows
    ]

    log_rows = tr.list_trading_logs(db, user.id, limit=100)
    logs = [
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
        for r in log_rows
    ]

    last_live_error: str | None = None
    last_live_error_at: str | None = None
    for r in log_rows:
        action = str(r.action or "").upper()
        if action in ("ERROR", "LIVE_SKIPPED", "ORDER_REJECTED") or action.startswith("LIVE_") and "FAIL" in action:
            last_live_error = str(r.message or action)
            last_live_error_at = _iso(r.created_at)
            break

    return DashboardOut(
        config=cfg,
        algo_running=bool(row.algo_running),
        trading_mode=(row.trading_mode or "PAPER").upper(),
        quotes=quotes,
        grid_levels=grid_levels,
        reference_price=parsed["reference_price"],
        position_lots=position_lots,
        realized_pnl=float(runtime.get("realizedPnl") or 0),
        unrealized_pnl=round(unrealized, 2),
        current_market_price=current_price,
        next_action_level=runtime.get("nextActionLevel"),
        active_trades=active_trades,
        completed_trades=completed_trades,
        logs=logs,
        last_live_error=last_live_error,
        last_live_error_at=last_live_error_at,
    )


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
    cfg = tr.load_config_dict(db, user.id)
    parsed = parse_strategy_config(cfg)
    quote = get_quote_by_key(parsed["market"])
    mark = float(quote.price if quote and quote.price > 0 else 0)
    rows = tr.list_open_positions(db, user.id)
    out: list[ActivePositionOut] = []
    for p in rows:
        st = "PENDING_FILL" if p.trading_mode == "LIVE" and float(p.entry_price or 0) <= 0 else "OPEN"
        px = mark if mark > 0 else float(p.entry_price or 0)
        entry = float(p.entry_price or 0.0)
        qty = int(p.quantity)
        pnl = (px - entry) * qty if entry > 0 else 0.0
        out.append(
            ActivePositionOut(
                id=p.id,
                leg_id=p.leg_id,
                side=p.side,
                strike=float(p.strike),
                lots=int(p.lots),
                quantity=qty,
                entry_price=entry,
                current_price=px,
                pnl=pnl,
                status=st,
                trading_mode=p.trading_mode,
                entry_time=_iso(p.entry_time),
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
        )
        for r in rows
    ]


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


@router.post("/backtest/run", response_model=GridBacktestOut)
def run_backtest(body: GridBacktestRunIn, _user: User = Depends(get_current_user)):
    """Run MCX grid backtest on Angel historical 1-min candles."""
    try:
        result = run_grid_backtest(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}") from exc
    return result
