"""Trading settings, dashboard, and backtest for Strategy 3."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    ActivePositionOut,
    BreakoutBacktestOut,
    BreakoutBacktestRunIn,
    CompletedPositionOut,
    DashboardOut,
    TradingLogOut,
    TradingSettingsOut,
    TradingSettingsPut,
    WindowLegOut,
    WindowOut,
)
from app.services import trading_repository as tr
from app.services.breakout_backtest import run_breakout_backtest
from app.services.breakout_logic import (
    build_trade_windows,
    default_config,
    nearest_itm_ce_strike,
    nearest_itm_pe_strike,
    parse_config,
)
from app.services.sensex_expiry import get_expiry_info
from app.services.sensex_quote import fetch_sensex_live_quote, settings_parsed_tokens

router = APIRouter(prefix="/trading", tags=["trading"])


def _iso(dt: Any) -> str | None:
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


_SENSEX_DASH_CACHE: dict[str, Any] = {"t": 0.0, "price": 0.0, "open": False, "source": "unconfigured", "err": None}
_SENSEX_DASH_TTL_SEC = 1.0


def _sensex_from_quote() -> tuple[float, bool, str, str | None]:
    from app.config import settings
    import time as _time

    now = _time.monotonic()
    if (
        float(_SENSEX_DASH_CACHE["price"] or 0) > 0
        and now - float(_SENSEX_DASH_CACHE["t"] or 0) < _SENSEX_DASH_TTL_SEC
    ):
        return (
            float(_SENSEX_DASH_CACHE["price"]),
            bool(_SENSEX_DASH_CACHE["open"]),
            str(_SENSEX_DASH_CACHE["source"]),
            _SENSEX_DASH_CACHE["err"],
        )

    raw = fetch_sensex_live_quote(
        exchange_tokens=settings_parsed_tokens(),
        mode=(settings.angel_quote_mode or "LTP").upper(),
    )
    fetched = raw.get("fetched") if isinstance(raw.get("fetched"), list) else []
    row = fetched[0] if fetched and isinstance(fetched[0], dict) else {}
    price = 0.0
    for key in ("ltp", "Ltp", "close", "Close"):
        try:
            val = float(row.get(key) or 0)
            if val > 0:
                price = val
                break
        except (TypeError, ValueError):
            pass
    source = str(raw.get("quote_source") or row.get("quote_source") or "live")
    # Keep Angel message whenever quote is not live so Generate Token can appear.
    err = None
    if not raw.get("angel_ok") or source.lower() not in ("live",):
        msg = raw.get("angel_message")
        err = str(msg) if msg else ("Angel quote unavailable — regenerate token" if source.lower() != "live" else None)
        if raw.get("token_expired") and not err:
            err = "Angel SmartAPI token expired"
    _SENSEX_DASH_CACHE.update(
        {"t": now, "price": price, "open": bool(raw.get("market_open")), "source": source, "err": err}
    )
    return float(price), bool(raw.get("market_open")), source, err


def _leg_out_from_runtime(side: str, leg: dict[str, Any]) -> WindowLegOut:
    return WindowLegOut(
        side=side,
        strike=float(leg.get("strike") or 0),
        premium_close=float(leg.get("premiumClose") or 0),
        entry_pct=leg.get("entryPct"),
        entry_price=leg.get("entryPrice"),
        target_price=leg.get("tp"),
        stop_price=leg.get("sl"),
        tradable=str(leg.get("state")) in ("ARMED", "OPEN"),
        skip_reason=str(leg.get("status") or "") or None,
    )


def _build_windows_from_runtime(runtime: dict[str, Any]) -> list[WindowOut] | None:
    from app.services.strategy3_trading_engine import _session_date

    if str(runtime.get("sessionDate") or "") != _session_date():
        return None
    windows = runtime.get("windows")
    if not isinstance(windows, list) or not windows:
        return None
    out: list[WindowOut] = []
    for w in windows:
        legs = w.get("legs") if isinstance(w.get("legs"), dict) else {}
        ce = legs.get("CE") if isinstance(legs.get("CE"), dict) else None
        pe = legs.get("PE") if isinstance(legs.get("PE"), dict) else None
        out.append(
            WindowOut(
                index=int(w.get("index") or 0),
                start_hhmm=str(w.get("start") or ""),
                reference_close=w.get("refClose"),
                ce=_leg_out_from_runtime("CE", ce) if ce else None,
                pe=_leg_out_from_runtime("PE", pe) if pe else None,
            )
        )
    return out


def _build_windows_preview(cfg: dict[str, Any], reference: float) -> list[WindowOut]:
    windows = build_trade_windows(
        str(cfg.get("startTime") or "14:35"),
        count=int(cfg.get("windowCount") or 3),
        gap_minutes=int(cfg.get("windowGapMinutes") or 10),
    )
    out: list[WindowOut] = []
    for w in windows:
        ref = reference if reference > 0 else 77136.0
        ce_strike = nearest_itm_ce_strike(ref)
        pe_strike = nearest_itm_pe_strike(ref)
        pending = "Awaiting 10m candle close" if reference > 0 else "Awaiting SENSEX price"
        out.append(
            WindowOut(
                index=w.index,
                start_hhmm=w.start_hhmm,
                reference_close=None,
                ce=WindowLegOut(side="CE", strike=ce_strike, skip_reason=pending),
                pe=WindowLegOut(side="PE", strike=pe_strike, skip_reason=pending),
            )
        )
    return out


@router.get("/settings", response_model=TradingSettingsOut)
def get_trading_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = tr.get_or_create_strategy_settings(db, user.id)
    cfg = tr.load_config_dict(db, user.id)
    if not cfg:
        cfg = default_config()
    return TradingSettingsOut(
        config=cfg,
        algo_running=bool(row.algo_running),
        trading_mode=(row.trading_mode or "PAPER").upper(),
        expiry_info=get_expiry_info(),
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
    if body.config is not None:
        existing = tr.load_config_dict(db, user.id) or default_config()
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

    cfg = tr.load_config_dict(db, user.id) or default_config()
    return TradingSettingsOut(
        config=cfg,
        algo_running=new_run,
        trading_mode=new_mode,
        expiry_info=get_expiry_info(),
    )


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = tr.get_or_create_strategy_settings(db, user.id)
    cfg = parse_config(tr.load_config_dict(db, user.id) or default_config())

    sensex_price, sensex_open, sensex_source, sensex_error = _sensex_from_quote()

    active_rows = tr.list_open_positions(db, user.id)
    completed_rows = tr.list_completed_positions(db, user.id, limit=50)
    logs_rows = tr.list_trading_logs(db, user.id, limit=80)

    realized = sum(float(p.pnl or 0) for p in completed_rows)
    today_realized = tr.sum_completed_pnl_today_ist(db, user.id)

    # Mark open option positions at their own option LTP (batched), not the index price.
    option_ltps: dict[str, float] = {}
    tokens = [str(p.symbol_token) for p in active_rows if p.symbol_token]
    if tokens:
        from app.services.strategy3_trading_engine import fetch_bfo_ltps

        option_ltps = fetch_bfo_ltps(list(dict.fromkeys(tokens)))

    unrealized = 0.0
    active_trades: list[ActivePositionOut] = []
    for p in active_rows:
        entry = float(p.entry_price or 0)
        mark = float(option_ltps.get(str(p.symbol_token or "")) or 0.0)
        if mark <= 0:
            mark = entry
        qty = int(p.quantity or 0)
        pnl = (mark - entry) * qty if entry > 0 else 0.0
        unrealized += pnl
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
                tp=float(p.tp) if p.tp is not None else None,
                trading_mode=p.trading_mode,
                trading_symbol=p.trading_symbol,
                entry_time=_iso(p.entry_time),
            )
        )

    completed_trades = [
        CompletedPositionOut(
            id=p.id,
            leg_id=p.leg_id,
            side=p.side,
            strike=float(p.strike),
            entry_price=float(p.entry_price),
            exit_price=float(p.exit_price) if p.exit_price is not None else None,
            pnl=float(p.pnl) if p.pnl is not None else None,
            exit_reason=p.exit_reason,
            trading_mode=p.trading_mode,
            trading_symbol=p.trading_symbol,
            entry_time=_iso(p.entry_time),
            exit_time=_iso(p.exit_time),
        )
        for p in completed_rows
    ]

    logs = [
        TradingLogOut(
            id=lg.id,
            created_at=_iso(lg.created_at) or "",
            mode=lg.mode,
            leg=lg.leg,
            action=lg.action,
            symbol=lg.symbol,
            strike=float(lg.strike) if lg.strike is not None else None,
            quantity=lg.quantity,
            entry_price=float(lg.entry_price) if lg.entry_price is not None else None,
            exit_price=float(lg.exit_price) if lg.exit_price is not None else None,
            pnl=float(lg.pnl) if lg.pnl is not None else None,
            status=lg.status,
            message=lg.message,
        )
        for lg in logs_rows
    ]

    runtime = cfg.get("strategy3_runtime") if isinstance(cfg.get("strategy3_runtime"), dict) else {}
    windows = _build_windows_from_runtime(runtime or {}) or _build_windows_preview(cfg, sensex_price)

    return DashboardOut(
        sensex_price=sensex_price,
        sensex_market_open=sensex_open,
        sensex_source=sensex_source,
        sensex_error=sensex_error,
        algo_running=bool(row.algo_running),
        trading_mode=(row.trading_mode or "PAPER").upper(),
        config=cfg,
        expiry_info=get_expiry_info(),
        windows=windows,
        realized_pnl=round(realized, 2),
        unrealized_pnl=round(unrealized, 2),
        today_realized_pnl=round(today_realized, 2),
        today_pnl=round(today_realized + unrealized, 2),
        active_trades=active_trades,
        completed_trades=completed_trades,
        logs=logs,
    )


@router.post("/legs/{leg_id}/close")
def close_leg_manual(
    leg_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manual close from dashboard. LIVE places a broker MARKET SELL before closing the row."""
    from app.config import settings
    from app.services import angel_orders

    lid = (leg_id or "").strip().upper()
    pos = tr.get_open_position_by_leg(db, user.id, lid)
    if not pos:
        raise HTTPException(status_code=404, detail="No open position for this leg")

    entry = float(pos.entry_price or 0)
    qty = int(pos.quantity or 0)
    mode = (pos.trading_mode or "PAPER").upper()
    # Exit at the option's own LTP; broker fill overrides this for LIVE.
    exit_px = entry
    if pos.symbol_token:
        from app.services.strategy3_trading_engine import fetch_bfo_ltps

        ltp = float(fetch_bfo_ltps([str(pos.symbol_token)]).get(str(pos.symbol_token)) or 0.0)
        if ltp > 0:
            exit_px = ltp

    if mode == "LIVE":
        if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
            raise HTTPException(status_code=400, detail="Angel One not configured — cannot close LIVE trade at broker")
        if not pos.trading_symbol or not pos.symbol_token or qty <= 0:
            raise HTTPException(status_code=400, detail="Position has no broker symbol/token — cannot close at broker")
        headers = dict(
            api_key=settings.angel_api_key.strip(),
            jwt_token=settings.angel_jwt_token.strip(),
            source_id=(settings.angel_source_id or "WEB").strip(),
            client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
            client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
            mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
            user_type=(settings.angel_user_type or "USER").strip(),
        )
        try:
            from app.services.strategy3_trading_engine import _product_type_for

            raw = angel_orders.place_market_order(
                exchange=(pos.exchange or "BFO").upper(),
                tradingsymbol=pos.trading_symbol,
                symboltoken=str(pos.symbol_token),
                transaction_type="SELL",
                quantity=qty,
                product_type=_product_type_for(tr.load_config_dict(db, user.id)),
                timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
                **headers,
            )
            order_id, _ok, broker_msg = angel_orders.extract_place_ack(raw)
            if not order_id:
                raise RuntimeError(broker_msg or "Angel placeOrder returned no order id")
            outcome = angel_orders.await_order_terminal(
                order_id=order_id,
                timeout_sec=min(8.0, float(settings.angel_request_timeout_sec or 15.0)),
                poll_interval_sec=0.1,
                cancel_if_unfilled=True,
                **headers,
            )
            if not outcome.filled:
                raise RuntimeError(f"Broker {outcome.status}: {outcome.message or broker_msg}")
            if float(outcome.average_price or 0) > 0:
                exit_px = float(outcome.average_price)
            tr.append_trading_log(
                db,
                user_id=user.id,
                mode=mode,
                leg=lid,
                action="LIVE_MANUAL_CLOSE",
                symbol=pos.trading_symbol,
                quantity=qty,
                exit_price=exit_px,
                status="COMPLETE",
                message=f"Manual close SELL FILLED @ {exit_px:.2f}"[:900],
            )
        except (RuntimeError, ValueError) as exc:
            tr.append_trading_log(
                db,
                user_id=user.id,
                mode=mode,
                leg=lid,
                action="ERROR",
                symbol=pos.trading_symbol,
                quantity=qty,
                message=f"Manual close rejected by broker: {exc}"[:900],
            )
            raise HTTPException(status_code=502, detail=f"Broker close failed: {exc}") from exc

    pnl = (exit_px - entry) * qty if entry > 0 else 0.0
    tr.close_position(db, pos, exit_price=exit_px, exit_reason="MANUAL_CLOSE", pnl=pnl)
    tr.append_trading_log(
        db,
        user_id=user.id,
        mode=mode,
        leg=lid,
        action="MANUAL_CLOSE",
        symbol=pos.trading_symbol,
        quantity=qty,
        entry_price=entry,
        exit_price=exit_px,
        pnl=pnl,
        message=f"Manual close @ {exit_px:.2f}"[:900],
    )
    return {"ok": True}


@router.post("/positions/close-all")
def close_all_positions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    positions = tr.list_open_positions(db, user.id)
    if not positions:
        raise HTTPException(status_code=404, detail="No active trades to close")

    # Prevent any strategy worker from opening another trade during bulk exit.
    tr.save_strategy_settings(db, user.id, algo_running=False)
    closed = 0
    for pos in positions:
        try:
            close_leg_manual(pos.leg_id, user, db)
            closed += 1
        except HTTPException as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Closed {closed} of {len(positions)} trades. {pos.leg_id} failed: {exc.detail}",
            ) from exc
    return {"ok": True, "closed": closed}


@router.delete("/logs")
def clear_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = tr.delete_all_trading_logs(db, user.id)
    return {"ok": True, "deleted": n}


@router.delete("/positions/completed")
def clear_completed_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = tr.delete_all_completed_positions(db, user.id)
    return {"ok": True, "deleted": n}


@router.post("/backtest/run", response_model=BreakoutBacktestOut)
def post_backtest_run(body: BreakoutBacktestRunIn, user: User = Depends(get_current_user)):
    _ = user
    try:
        cfg = parse_config(body.config or {})
        result = run_breakout_backtest({
            "fromDate": body.fromDate,
            "toDate": body.toDate,
            "config": cfg,
        })
        return BreakoutBacktestOut(**result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e
