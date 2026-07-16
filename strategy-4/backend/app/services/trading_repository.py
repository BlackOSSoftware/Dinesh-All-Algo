"""Persistence helpers for strategy settings, positions, and trading logs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import StrategySettings, TradePosition, TradingLog


def _ist_tz():
    try:
        return ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=5, minutes=30))


def leg_has_entry_today_ist(db: Session, user_id: int, leg_id: str) -> bool:
    """True if any position (open or closed) for this leg was opened since IST midnight today."""
    tz = _ist_tz()
    now = datetime.now(tz)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    n = db.scalar(
        select(func.count())
        .select_from(TradePosition)
        .where(
            TradePosition.user_id == user_id,
            TradePosition.leg_id == leg_id,
            TradePosition.entry_time >= start_utc,
        )
    )
    return int(n or 0) > 0


# Exits after which the same leg must not re-open the same IST day (even if legEntryMode is multi).
_SESSION_BLOCKING_EXIT_REASONS: tuple[str, ...] = (
    "TP_HIT",
    "PUT_SL_HIT",
    "CALL_SL_HIT",
    "AUTO_EXIT",
    "END_TIME",  # legacy session-end marker
    "SENSEX_BASE_SL",
)


def leg_has_session_blocking_exit_today_ist(db: Session, user_id: int, leg_id: str) -> bool:
    """True if this leg was closed today (IST) with TP / basket SL / session auto-exit."""
    tz = _ist_tz()
    now = datetime.now(tz)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    n = db.scalar(
        select(func.count())
        .select_from(TradePosition)
        .where(
            TradePosition.user_id == user_id,
            TradePosition.leg_id == leg_id,
            TradePosition.status == "CLOSED",
            TradePosition.exit_time >= start_utc,
            TradePosition.exit_reason.in_(_SESSION_BLOCKING_EXIT_REASONS),
        )
    )
    return int(n or 0) > 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_strategy_settings(db: Session, user_id: int) -> StrategySettings:
    row = db.scalar(select(StrategySettings).where(StrategySettings.user_id == user_id))
    if row:
        return row
    row = StrategySettings(
        user_id=user_id,
        config_json="{}",
        algo_running=False,
        trading_mode="PAPER",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def load_config_dict(db: Session, user_id: int) -> dict[str, Any]:
    row = get_or_create_strategy_settings(db, user_id)
    try:
        data = json.loads(row.config_json or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def merge_strategy_runtime(db: Session, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge engine runtime fields into config_json (adaptive high/low, phase, etc.)."""
    cfg = load_config_dict(db, user_id)
    rt = cfg.get("strategy_runtime")
    if not isinstance(rt, dict):
        rt = {}
    rt.update(patch)
    cfg["strategy_runtime"] = rt
    if rt.get("adaptive_high") is not None:
        cfg["adaptiveHigh"] = rt["adaptive_high"]
    if rt.get("adaptive_low") is not None:
        cfg["adaptiveLow"] = rt["adaptive_low"]
    save_strategy_settings(db, user_id, config=cfg)
    return cfg


def load_strategy_runtime(cfg: dict[str, Any]) -> dict[str, Any]:
    rt = cfg.get("strategy_runtime")
    return dict(rt) if isinstance(rt, dict) else {}


def save_strategy_settings(
    db: Session,
    user_id: int,
    *,
    config: dict[str, Any] | None = None,
    algo_running: bool | None = None,
    trading_mode: str | None = None,
) -> StrategySettings:
    row = get_or_create_strategy_settings(db, user_id)
    if config is not None:
        row.config_json = json.dumps(config, separators=(",", ":"), default=str)
    if algo_running is not None:
        row.algo_running = bool(algo_running)
    if trading_mode is not None:
        tm = (trading_mode or "PAPER").strip().upper()
        row.trading_mode = "LIVE" if tm == "LIVE" else "PAPER"
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def append_trading_log(
    db: Session,
    *,
    user_id: int,
    mode: str,
    leg: str,
    action: str,
    symbol: str | None = None,
    strike: float | None = None,
    quantity: int | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    pnl: float | None = None,
    status: str | None = None,
    order_id: str | None = None,
    message: str | None = None,
) -> TradingLog:
    log = TradingLog(
        user_id=user_id,
        mode=(mode or "PAPER")[:8],
        leg=(leg or "-")[:16],
        action=(action or "-")[:32],
        symbol=symbol[:128] if symbol else None,
        strike=strike,
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        status=status[:32] if status else None,
        order_id=order_id[:64] if order_id else None,
        message=message,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_trading_logs(db: Session, user_id: int, limit: int = 500) -> list[TradingLog]:
    q = (
        select(TradingLog)
        .where(TradingLog.user_id == user_id)
        .order_by(TradingLog.id.desc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.scalars(q).all())


def get_open_position_by_leg(db: Session, user_id: int, leg_id: str) -> TradePosition | None:
    return db.scalar(
        select(TradePosition).where(
            TradePosition.user_id == user_id,
            TradePosition.leg_id == leg_id,
            TradePosition.status == "OPEN",
        )
    )


def list_open_positions(db: Session, user_id: int) -> list[TradePosition]:
    q = (
        select(TradePosition)
        .where(
            TradePosition.user_id == user_id,
            TradePosition.status == "OPEN",
        )
        .order_by(TradePosition.entry_time.asc(), TradePosition.id.asc())
    )
    return list(db.scalars(q).all())


def list_completed_positions(db: Session, user_id: int, limit: int = 200) -> list[TradePosition]:
    q = (
        select(TradePosition)
        .where(
            TradePosition.user_id == user_id,
            TradePosition.status == "CLOSED",
        )
        .order_by(TradePosition.exit_time.desc(), TradePosition.id.desc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.scalars(q).all())


def sum_completed_pnl_today_ist(db: Session, user_id: int) -> float:
    """Total realized PnL of positions closed since IST midnight today."""
    tz = _ist_tz()
    now = datetime.now(tz)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    total = db.scalar(
        select(func.coalesce(func.sum(TradePosition.pnl), 0.0)).where(
            TradePosition.user_id == user_id,
            TradePosition.status == "CLOSED",
            TradePosition.exit_time >= start_utc,
        )
    )
    return float(total or 0.0)


def delete_all_completed_positions(db: Session, user_id: int) -> int:
    """Delete all CLOSED trade rows for this user. Returns approximate deleted count."""
    res = db.execute(
        delete(TradePosition).where(
            TradePosition.user_id == user_id,
            TradePosition.status == "CLOSED",
        ),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    return int(res.rowcount or 0)


def delete_all_trading_logs(db: Session, user_id: int) -> int:
    """Delete all trading log rows for this user."""
    res = db.execute(
        delete(TradingLog).where(TradingLog.user_id == user_id),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    return int(res.rowcount or 0)


def reset_algo_session(db: Session, user_id: int, *, current_price: float = 0.0) -> dict[str, Any]:
    """Fresh breakout session when algo is enabled: clear runtime state and close open DB positions."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from app.services.breakout_logic import fresh_breakout_runtime

    try:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except ZoneInfoNotFoundError:
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")

    cfg = load_config_dict(db, user_id)
    runtime = fresh_breakout_runtime(session_date=today, last_price=current_price)
    cfg["breakout_runtime"] = runtime
    save_strategy_settings(db, user_id, config=cfg)

    mark = current_price
    for pos in list_open_positions(db, user_id):
        px = mark if mark > 0 else float(pos.entry_price or 0)
        entry = float(pos.entry_price or 0.0)
        lots = int(pos.lots or 0)
        pnl = (px - entry) * lots if entry > 0 else 0.0
        close_position(db, pos, exit_price=px, exit_reason="ALGO_RESTART", pnl=pnl)

    return runtime


def create_open_position(db: Session, pos: TradePosition) -> TradePosition:
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


def close_position(
    db: Session,
    pos: TradePosition,
    *,
    exit_price: float,
    exit_reason: str,
    pnl: float,
) -> TradePosition:
    pos.exit_price = exit_price
    pos.exit_time = _utcnow()
    pos.exit_reason = exit_reason[:64]
    pos.pnl = pnl
    pos.status = "CLOSED"
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


def update_position_fields(db: Session, pos: TradePosition, **kwargs: Any) -> TradePosition:
    for k, v in kwargs.items():
        if hasattr(pos, k) and v is not None:
            setattr(pos, k, v)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos
