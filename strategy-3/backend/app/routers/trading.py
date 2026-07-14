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
    source = str(row.get("quote_source") or "live")
    err = raw.get("angel_message") if not raw.get("angel_ok") else None
    _SENSEX_DASH_CACHE.update(
        {"t": now, "price": price, "open": bool(raw.get("market_open")), "source": source, "err": err}
    )
    return float(price), bool(raw.get("market_open")), source, err


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
                reference_close=reference if reference > 0 else None,
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
    unrealized = 0.0
    active_trades: list[ActivePositionOut] = []
    for p in active_rows:
        mark = sensex_price if sensex_price > 0 else float(p.entry_price or 0)
        entry = float(p.entry_price or 0)
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

    windows = _build_windows_preview(cfg, sensex_price)

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
        active_trades=active_trades,
        completed_trades=completed_trades,
        logs=logs,
    )


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
