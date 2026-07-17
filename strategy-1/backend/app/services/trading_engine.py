"""
Background trading engine: SENSEX Adaptive Trend Averaging (single leg SOB), paper + LIVE Angel.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.models import StrategySettings, TradePosition
from app.services import trading_repository as tr
from app.services.market_ltp import get_index_ltp_cached
from app.services.sensex_adaptive_trend import tick_sensex_adaptive_trend_session

LOG = logging.getLogger(__name__)

_engine_task: asyncio.Task[None] | None = None
_stop = asyncio.Event()
_prev_index_ltp: float | None = None
_last_market_ok: bool | None = None
_logged_engine_start: bool = False


def _synthetic_option_mark(pos: TradePosition, index_ltp: float) -> float:
    """Mark long option from index move vs entry (paper + LIVE PnL proxy)."""
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


def _close_open(db: Session, pos: TradePosition, reason: str, exit_px: float) -> None:
    entry = float(pos.entry_price or 0.0)
    qty = int(pos.quantity)
    if entry <= 0:
        pnl = 0.0
        exit_px = 0.0
    else:
        pnl = (exit_px - entry) * qty
    tr.close_position(db, pos, exit_price=exit_px, exit_reason=reason, pnl=pnl)
    act = reason[:32]
    tr.append_trading_log(
        db,
        user_id=pos.user_id,
        mode=pos.trading_mode,
        leg=pos.leg_id,
        action=act,
        symbol=pos.trading_symbol,
        strike=pos.strike,
        quantity=qty,
        entry_price=entry,
        exit_price=exit_px,
        pnl=pnl,
        status=act,
        order_id=pos.order_id,
        message=reason[:900],
    )


def manual_close_leg(db: Session, user_id: int, leg_id: str) -> None:
    lid = (leg_id or "").strip().upper()
    pos = tr.get_open_position_by_leg(db, user_id, lid)
    if not pos:
        raise ValueError("NO_OPEN_POSITION")
    ltp, _, ok = get_index_ltp_cached()
    idx = float(ltp) if ok and ltp is not None else float(pos.underlying_at_entry or pos.range_level)
    # _close_sob places the broker MARKET SELL in LIVE mode and waits for fill
    # confirmation before closing the DB row (paper closes at synthetic mark).
    from app.services.sensex_option_buy import _close_sob

    if not _close_sob(db, pos, "MANUAL_CLOSE", idx):
        raise ValueError("Broker close failed — exit SELL was rejected or not filled. Check logs.")

    # Wipe open-cycle runtime so the engine does not keep phantom TP/SL/trailing state.
    tr.merge_strategy_runtime(
        db,
        user_id,
        {
            "flat_mode": None,
            "trail_extreme": None,
            "core_lots": 0,
            "avg_lots": 0,
            "sl_level": None,
            "t1_level_avg": None,
            "t1_level_core": None,
            "avg_t1_done": None,
            "core_t1_done": None,
            "cycle_extreme": None,
            "entries_filled": None,
        },
    )


def _tick_session(db: Session, st_row: StrategySettings, cfg: dict[str, Any], index_ltp: float) -> None:
    global _prev_index_ltp
    tick_sensex_adaptive_trend_session(db, st_row, cfg, index_ltp, _prev_index_ltp)


def tick_once() -> None:
    global _prev_index_ltp, _last_market_ok, _logged_engine_start
    ltp, _detail, ok = get_index_ltp_cached()
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(StrategySettings).where(StrategySettings.algo_running.is_(True))).all())
        if not _logged_engine_start and rows:
            LOG.info("Trading engine serving %d active strategy row(s)", len(rows))
            _logged_engine_start = True

        # Market-data connect/lost transitions are tracked internally only
        # (no MARKET_DATA_CONNECTED / MARKET_DATA_LOST rows in trading logs).
        _last_market_ok = bool(ok and ltp is not None)

        if ltp is None or not ok:
            return

        assert ltp is not None
        index_ltp = float(ltp)

        for st in rows:
            cfg = tr.load_config_dict(db, st.user_id)
            try:
                _tick_session(db, st, cfg, index_ltp)
            except Exception as exc:  # noqa: BLE001
                LOG.exception("User %s trading tick error", st.user_id)
                tr.append_trading_log(
                    db,
                    user_id=st.user_id,
                    mode=st.trading_mode,
                    leg="-",
                    action="ERROR",
                    message=str(exc)[:900],
                )

        _prev_index_ltp = index_ltp
    finally:
        db.close()


async def run_engine_loop() -> None:
    LOG.info("Trading engine loop started")
    while not _stop.is_set():
        try:
            await asyncio.to_thread(tick_once)
        except Exception:  # noqa: BLE001
            LOG.exception("tick_once crashed")
        try:
            await asyncio.wait_for(asyncio.sleep(0.02), timeout=1.0)
        except asyncio.CancelledError:
            break
    LOG.info("Trading engine loop stopped")


def start_trading_engine_task() -> asyncio.Task[None]:
    global _engine_task
    _stop.clear()
    if _engine_task and not _engine_task.done():
        return _engine_task
    _engine_task = asyncio.create_task(run_engine_loop(), name="trading-engine")
    return _engine_task


async def stop_trading_engine_task() -> None:
    global _engine_task
    _stop.set()
    if _engine_task and not _engine_task.done():
        _engine_task.cancel()
        try:
            await _engine_task
        except asyncio.CancelledError:
            pass
    _engine_task = None
