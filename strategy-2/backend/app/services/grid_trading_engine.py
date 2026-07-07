"""Background grid trading engine for Strategy 2 (MCX)."""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import StrategySettings, TradePosition, User
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.grid_logic import (
    grid_level_tolerance,
    grid_order_price,
    load_runtime,
    ltp_matches_grid_level,
    parse_strategy_config,
    process_price_tick,
    seed_runtime_market_price,
)
from app.services.mcx_instruments import get_instrument
from app.services.mcx_quotes import get_quote_by_key

LOG = logging.getLogger(__name__)

_TASK: asyncio.Task | None = None
_STOP = asyncio.Event()


def _ist_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except ZoneInfoNotFoundError:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = (value or "00:00").strip().split(":")
    h = int(parts[0]) if parts and parts[0].isdigit() else 0
    m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return h, m


def _in_session(start_time: str, end_time: str) -> bool:
    now = _ist_now()
    sh, sm = _parse_hhmm(start_time)
    eh, em = _parse_hhmm(end_time)
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=59, microsecond=999999)
    return start <= now <= end


def _angel_order_headers() -> dict[str, str]:
    return {
        "api_key": settings.angel_api_key.strip(),
        "jwt_token": settings.angel_jwt_token.strip(),
        "source_id": settings.angel_source_id,
        "client_local_ip": settings.angel_client_local_ip,
        "client_public_ip": settings.angel_client_public_ip,
        "mac_address": settings.angel_mac_address,
        "user_type": settings.angel_user_type,
    }


def _live_trading_ready(instrument) -> tuple[bool, str]:
    if not settings.angel_live_trading_enabled:
        return False, "ANGEL_LIVE_TRADING_ENABLED=false"
    if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
        return False, "Angel API key or JWT missing in .env"
    if not instrument or not instrument.configured:
        return False, "MCX instrument token/symbol not configured"
    return True, ""


def _extract_order_ack(raw: Any) -> tuple[str, bool, str]:
    """Accept Angel success payloads where `data` is either an object or a plain order-id string."""
    if not isinstance(raw, dict):
        return "", False, str(raw or "Invalid Angel order response")

    data = raw.get("data")
    order_id = ""
    if isinstance(data, dict):
        order_id = str(data.get("orderid") or data.get("orderId") or "").strip()
    elif data not in (None, ""):
        order_id = str(data).strip()

    if not order_id:
        order_id = str(raw.get("orderid") or raw.get("orderId") or "").strip()

    status = raw.get("status")
    ok = status is True or str(status or "").lower() in ("true", "success")
    message = str(raw.get("message") or raw.get("errorcode") or raw.get("errorCode") or raw)
    return order_id, ok, message


def _execute_live_order(
    db,
    *,
    user_id: int,
    instrument,
    mode: str,
    action: str,
    lots: int,
    grid_price: float,
    ltp_at_signal: float,
    level_id: str,
) -> str | None:
    if lots <= 0:
        return None
    ready, reason = _live_trading_ready(instrument)
    if not ready:
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=level_id,
            action="LIVE_SKIPPED",
            symbol=instrument.tradingsymbol if instrument else "-",
            message=reason[:900],
        )
        return None
    if grid_price <= 0:
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=level_id,
            action="LIVE_SKIPPED",
            symbol=instrument.tradingsymbol,
            message="Missing grid level price for LIMIT order"[:900],
        )
        return None
    qty = lots * instrument.lotsize
    tx = "BUY" if action in ("INITIAL_BUY", "REENTER", "ADD") else "SELL"
    limit_px = grid_order_price(grid_price)
    try:
        raw = angel_orders.place_order(
            exchange=instrument.exchange,
            tradingsymbol=instrument.tradingsymbol,
            symboltoken=instrument.token,
            transaction_type=tx,
            quantity=qty,
            product_type="CARRYFORWARD",
            limit_price=limit_px,
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
            **_angel_order_headers(),
        )
        order_id, ok, broker_msg = _extract_order_ack(raw)
        if not order_id and not ok:
            msg = broker_msg[:900]
            raise RuntimeError(msg or "Angel placeOrder returned no order id")
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=level_id,
            action=f"LIVE_{action}",
            symbol=instrument.tradingsymbol,
            quantity=qty,
            entry_price=limit_px if tx == "BUY" else None,
            exit_price=limit_px if tx == "SELL" else None,
            order_id=order_id or None,
            message=f"LIMIT @ {limit_px:.2f} · LTP {ltp_at_signal:.2f} · {broker_msg}"[:900],
        )
        return order_id or "OK"
    except Exception as exc:  # noqa: BLE001
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=level_id,
            action="ERROR",
            symbol=instrument.tradingsymbol,
            message=f"Live order failed: {exc}"[:900],
        )
        return None


def _position_pnl(entry: float, exit_or_mark: float, quantity: int) -> float:
    return (exit_or_mark - entry) * quantity if entry > 0 else 0.0


def _create_open_leg(
    db,
    *,
    user_id: int,
    instrument,
    mode: str,
    leg_id: str,
    lots: int,
    entry_px: float,
) -> None:
    if lots <= 0 or entry_px <= 0:
        return
    row = tr.get_open_position_by_leg(db, user_id, leg_id)
    qty = lots * instrument.lotsize
    if row:
        row.lots = int(row.lots or 0) + lots
        row.quantity = int(row.lots) * instrument.lotsize
        db.add(row)
        db.commit()
        return
    db.add(
        TradePosition(
            user_id=user_id,
            leg_id=leg_id[:32],
            trading_mode=mode,
            side="LONG",
            range_level=entry_px,
            strike=entry_px,
            lots=lots,
            quantity=qty,
            entry_price=entry_px,
            status="OPEN",
            exchange=instrument.exchange,
            trading_symbol=instrument.tradingsymbol,
            symbol_token=instrument.token,
        )
    )
    db.commit()


def _close_open_leg(
    db,
    *,
    user_id: int,
    instrument,
    leg_id: str,
    lots: int,
    exit_px: float,
    exit_reason: str,
    entry_px_hint: float = 0.0,
) -> None:
    if lots <= 0:
        return
    row = tr.get_open_position_by_leg(db, user_id, leg_id)
    if not row:
        return
    close_lots = min(lots, int(row.lots or 0))
    if close_lots <= 0:
        return
    entry = float(row.entry_price or entry_px_hint or exit_px)
    close_qty = close_lots * instrument.lotsize
    pnl = _position_pnl(entry, exit_px, close_qty)
    if close_lots >= int(row.lots or 0):
        tr.close_position(db, row, exit_price=exit_px, exit_reason=exit_reason, pnl=pnl)
        return
    row.lots = int(row.lots) - close_lots
    row.quantity = int(row.quantity) - close_qty
    db.add(row)
    closed = TradePosition(
        user_id=user_id,
        leg_id=leg_id[:32],
        trading_mode=row.trading_mode,
        side=row.side,
        range_level=float(row.range_level),
        strike=float(row.strike),
        lots=close_lots,
        quantity=close_qty,
        entry_price=entry,
        exit_price=exit_px,
        exit_time=datetime.now(timezone.utc),
        exit_reason=exit_reason[:64],
        pnl=pnl,
        status="CLOSED",
        exchange=row.exchange,
        trading_symbol=row.trading_symbol,
        symbol_token=row.symbol_token,
    )
    db.add(closed)
    db.commit()


def _record_upper_exit(
    db,
    *,
    user_id: int,
    instrument,
    mode: str,
    level_id: str,
    lots: int,
    exit_px: float,
    entry_px: float,
) -> None:
    """Upper grid exit: completed leg row + reduce BASE open lots."""
    if lots <= 0:
        return
    qty = lots * instrument.lotsize
    pnl = _position_pnl(entry_px, exit_px, qty)
    db.add(
        TradePosition(
            user_id=user_id,
            leg_id=level_id[:32],
            trading_mode=mode,
            side="LONG",
            range_level=exit_px,
            strike=exit_px,
            lots=lots,
            quantity=qty,
            entry_price=entry_px,
            exit_price=exit_px,
            exit_time=datetime.now(timezone.utc),
            exit_reason="EXIT",
            pnl=pnl,
            status="CLOSED",
            exchange=instrument.exchange,
            trading_symbol=instrument.tradingsymbol,
            symbol_token=instrument.token,
        )
    )
    base = tr.get_open_position_by_leg(db, user_id, "BASE")
    if base:
        reduce_qty = lots * instrument.lotsize
        if int(base.lots or 0) <= lots:
            tr.close_position(
                db,
                base,
                exit_price=exit_px,
                exit_reason="REDUCE",
                pnl=_position_pnl(float(base.entry_price or entry_px), exit_px, int(base.quantity or reduce_qty)),
            )
        else:
            base.lots = int(base.lots) - lots
            base.quantity = int(base.quantity) - reduce_qty
            db.add(base)
    db.commit()


def _migrate_legacy_grid_main(db, user_id: int) -> None:
    legacy = tr.get_open_position_by_leg(db, user_id, "GRID_MAIN")
    if not legacy:
        return
    existing_base = tr.get_open_position_by_leg(db, user_id, "BASE")
    if existing_base:
        tr.close_position(
            db,
            legacy,
            exit_price=float(legacy.entry_price or 0),
            exit_reason="MIGRATE",
            pnl=0.0,
        )
        return
    legacy.leg_id = "BASE"
    db.add(legacy)
    db.commit()


def _sync_positions_for_actions(
    db,
    *,
    user_id: int,
    instrument,
    mode: str,
    actions: list[dict[str, Any]],
    runtime: dict[str, Any],
    mark_price: float,
) -> None:
    """One open row per grid leg (BASE, D1, …); each add/exit updates the matching leg."""
    _migrate_legacy_grid_main(db, user_id)

    if not actions:
        position = int(runtime.get("positionLots") or 0)
        if position <= 0:
            for pos in tr.list_open_positions(db, user_id):
                entry = float(pos.entry_price or mark_price)
                qty = int(pos.quantity or 0)
                tr.close_position(
                    db,
                    pos,
                    exit_price=mark_price,
                    exit_reason="FLAT",
                    pnl=_position_pnl(entry, mark_price, qty),
                )
        return

    avg_entry = float(runtime.get("avgEntryPrice") or 0)

    for act in actions:
        action = str(act.get("action") or "")
        level_id = str(act.get("level") or "")
        lots = abs(int(act.get("lotsDelta") or 0))
        fill_px = grid_order_price(float(act.get("levelPrice") or 0))
        if lots <= 0 or fill_px <= 0:
            continue

        if action == "INITIAL_BUY":
            _create_open_leg(
                db,
                user_id=user_id,
                instrument=instrument,
                mode=mode,
                leg_id="BASE",
                lots=lots,
                entry_px=fill_px,
            )
        elif action == "ADD":
            _create_open_leg(
                db,
                user_id=user_id,
                instrument=instrument,
                mode=mode,
                leg_id=level_id,
                lots=lots,
                entry_px=fill_px,
            )
        elif action == "REENTER":
            target = str(act.get("reenterU") or level_id)
            _create_open_leg(
                db,
                user_id=user_id,
                instrument=instrument,
                mode=mode,
                leg_id=target,
                lots=lots,
                entry_px=fill_px,
            )
        elif action == "EXIT":
            unwind_d = act.get("unwindD")
            if unwind_d:
                _close_open_leg(
                    db,
                    user_id=user_id,
                    instrument=instrument,
                    leg_id=str(unwind_d),
                    lots=lots,
                    exit_px=fill_px,
                    exit_reason=f"UNWIND@{level_id}",
                )
            elif level_id.startswith("U"):
                entry_px = avg_entry if avg_entry > 0 else fill_px
                _record_upper_exit(
                    db,
                    user_id=user_id,
                    instrument=instrument,
                    mode=mode,
                    level_id=level_id,
                    lots=lots,
                    exit_px=fill_px,
                    entry_px=entry_px,
                )
            else:
                _close_open_leg(
                    db,
                    user_id=user_id,
                    instrument=instrument,
                    leg_id=level_id,
                    lots=lots,
                    exit_px=fill_px,
                    exit_reason="EXIT",
                )


def process_user_tick(db, user_id: int) -> None:
    row = db.scalar(select(StrategySettings).where(StrategySettings.user_id == user_id))
    if not row or not row.algo_running:
        return

    cfg = tr.load_config_dict(db, user_id)
    parsed = parse_strategy_config(cfg)
    if parsed["reference_price"] <= 0 or parsed["grid_gap"] <= 0:
        return

    if not _in_session(parsed["start_time"], parsed["end_time"]):
        return

    instrument = get_instrument(parsed["market"])
    if not instrument:
        return

    quote = get_quote_by_key(parsed["market"])
    price = float(quote.price if quote else 0)
    if price <= 0:
        rt = load_runtime(cfg)
        price = float(rt.get("lastPrice") or 0)
    mode = (row.trading_mode or "PAPER").upper()
    if price <= 0 and mode == "PAPER" and parsed["reference_price"] > 0:
        price = parsed["reference_price"]
    if price <= 0:
        return

    runtime = load_runtime(cfg)
    runtime = seed_runtime_market_price(runtime, price)
    prev_runtime = copy.deepcopy(runtime)
    runtime, actions = process_price_tick({**cfg, "grid_runtime": runtime}, runtime, price)

    kept_actions: list[dict[str, Any]] = []
    live_failed = False

    grid_gap = parsed["grid_gap"]

    for act in actions:
        lots = abs(int(act.get("lotsDelta") or 0))
        level_px = float(act.get("levelPrice") or 0)
        if level_px <= 0:
            continue
        fill_px = grid_order_price(level_px)
        log_msg = str(act.get("message") or "")
        log_msg = f"{log_msg} | Grid {fill_px:.2f} · LTP {price:.2f}"[:900]

        if mode == "LIVE" and lots > 0:
            if level_px <= 0 or not ltp_matches_grid_level(price, level_px, grid_gap):
                tr.append_trading_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    leg=str(act.get("level") or "-"),
                    action="LIVE_SKIPPED",
                    symbol=instrument.tradingsymbol,
                    message=(
                        f"LTP {price:.2f} not at grid {level_px:.2f} "
                        f"(tol ±{grid_level_tolerance(grid_gap):.2f}) — no broker order"
                    )[:900],
                )
                live_failed = True
                break
            if (
                _execute_live_order(
                    db,
                    user_id=user_id,
                    instrument=instrument,
                    mode=mode,
                    action=str(act.get("action") or ""),
                    lots=lots,
                    grid_price=fill_px,
                    ltp_at_signal=price,
                    level_id=str(act.get("level") or "-"),
                )
                is None
            ):
                live_failed = True
                break

        kept_actions.append(act)
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=str(act.get("level") or "-"),
            action=str(act.get("action") or "GRID"),
            symbol=instrument.tradingsymbol,
            quantity=lots * instrument.lotsize,
            entry_price=fill_px if int(act.get("lotsDelta") or 0) > 0 else None,
            exit_price=fill_px if int(act.get("lotsDelta") or 0) < 0 else None,
            pnl=float(act.get("realizedPnl") or 0),
            message=log_msg,
        )

    if mode == "LIVE" and live_failed:
        runtime = prev_runtime
        kept_actions = []
    else:
        cfg["grid_runtime"] = runtime
        tr.save_strategy_settings(db, user_id, config=cfg)
        _sync_positions_for_actions(
            db,
            user_id=user_id,
            instrument=instrument,
            mode=mode,
            actions=kept_actions,
            runtime=runtime,
            mark_price=price,
        )


async def _engine_loop() -> None:
    LOG.info("[GridEngine] Strategy 2 grid engine started")
    while not _STOP.is_set():
        try:
            db = SessionLocal()
            try:
                users = db.scalars(
                    select(StrategySettings.user_id).where(StrategySettings.algo_running.is_(True))
                ).all()
                for uid in users:
                    try:
                        process_user_tick(db, int(uid))
                    except Exception as exc:  # noqa: BLE001
                        LOG.exception("[GridEngine] tick failed user=%s: %s", uid, exc)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("[GridEngine] loop error: %s", exc)
        try:
            await asyncio.wait_for(_STOP.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
    LOG.info("[GridEngine] stopped")


def start_grid_engine_task() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    _STOP.clear()
    _TASK = asyncio.create_task(_engine_loop())


async def stop_grid_engine_task() -> None:
    global _TASK
    _STOP.set()
    if _TASK:
        try:
            await asyncio.wait_for(_TASK, timeout=10.0)
        except asyncio.TimeoutError:
            _TASK.cancel()
        _TASK = None
