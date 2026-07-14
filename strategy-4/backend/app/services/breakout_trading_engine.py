"""Background breakout trading engine for Strategy 4 (MCX)."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import StrategySettings, TradePosition
from app.services import angel_orders
from app.services import trading_repository as tr
from app.services.breakout_backtest import _fetch_day_candles
from app.services.breakout_logic import (
    find_reference_candle,
    fresh_breakout_runtime,
    load_runtime,
    parse_strategy_config,
    process_price_tick,
    set_reference_from_candle,
)
from app.services.mcx_instruments import get_instrument
from app.services.mcx_quotes import get_quote_by_key

LOG = logging.getLogger(__name__)

_TASK: asyncio.Task | None = None
_STOP = asyncio.Event()
_REF_FETCH_AT: dict[str, float] = {}
_TICK_PRICE: dict[int, tuple[str, float, float]] = {}


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
    """True when now is inside [start, end]. Supports overnight windows (end < start)."""
    now = _ist_now()
    sh, sm = _parse_hhmm(start_time)
    eh, em = _parse_hhmm(end_time)
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=59, microsecond=999999)
    if end < start:
        # e.g. 18:29 → 02:30 next calendar morning
        return now >= start or now <= end
    return start <= now <= end


def _runtime_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = (
        "phase",
        "sessionDate",
        "referencePrice",
        "buyTrigger",
        "sellTrigger",
        "side",
        "entryPrice",
        "tpPrice",
        "slPrice",
        "isReverse",
        "tradeCount",
        "positionLots",
        "realizedPnl",
        "lastPrice",
        "prevPrice",
        "refCandleTime",
        "message",
        "reverseEntryBarTime",
    )
    for k in keys:
        if before.get(k) != after.get(k):
            return True
    return False


def _session_date() -> str:
    return _ist_now().strftime("%Y-%m-%d")


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
    """Normalize Angel success/reject payloads."""
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


def _ensure_daily_session(cfg: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    today = _session_date()
    if str(runtime.get("sessionDate") or "") != today:
        return fresh_breakout_runtime(session_date=today)
    return runtime


def _maybe_set_reference(db, user_id: int, cfg: dict[str, Any], runtime: dict[str, Any], parsed: dict[str, Any], instrument) -> dict[str, Any]:
    if _num(runtime.get("referencePrice")) > 0:
        return runtime

    phase = str(runtime.get("phase") or "")
    if phase not in ("IDLE", "WAIT_REF", "WAIT_BREAKOUT"):
        return runtime

    now = _ist_now()
    sh, sm = _parse_hhmm(parsed["start_time"])
    if now < now.replace(hour=sh, minute=sm, second=0, microsecond=0) + timedelta(minutes=1):
        rt = copy.copy(runtime)
        rt["phase"] = "WAIT_REF"
        rt["message"] = f"Waiting for reference candle at {parsed['start_time']}"
        return rt

    if not instrument or not instrument.configured:
        rt = copy.copy(runtime)
        rt["phase"] = str(rt.get("phase") or "WAIT_REF")
        rt["message"] = "MCX instrument token/symbol not configured — cannot fetch reference candle"
        return rt

    key = f"{user_id}:{_session_date()}"
    # Don't starve WAIT_BREAKOUT: only throttle Angel history calls, and keep retrying
    # until a reference candle is actually locked in.
    last_fetch = _REF_FETCH_AT.get(key, 0)
    if time.monotonic() - last_fetch < 15:
        return runtime
    _REF_FETCH_AT[key] = time.monotonic()

    try:
        candles = _fetch_day_candles(
            date=_session_date(),
            start_time=parsed["start_time"],
            end_time=parsed["end_time"],
            exchange=instrument.exchange,
            symboltoken=instrument.token,
        )
        ref = find_reference_candle(candles, parsed["start_time"])
        if ref:
            rt = set_reference_from_candle(runtime, ref, parsed)
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode="PAPER",
                leg="REF",
                action="REFERENCE_SET",
                symbol=instrument.tradingsymbol,
                entry_price=_num(ref.get("close")),
                message=str(rt.get("message") or "")[:900],
            )
            return rt
        rt = copy.copy(runtime)
        rt["phase"] = "WAIT_REF"
        rt["message"] = (
            f"No {parsed['start_time']} candle yet for {_session_date()} "
            f"({instrument.tradingsymbol}) — retrying"
        )
        return rt
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Reference candle fetch failed: %s", exc)
        rt = copy.copy(runtime)
        rt["phase"] = "WAIT_REF"
        rt["message"] = f"Reference fetch failed: {exc}"
        return rt
    return runtime


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _sync_position(
    db,
    *,
    user_id: int,
    instrument,
    mode: str,
    action: dict[str, Any],
    mark_price: float,
) -> None:
    act = str(action.get("action") or "")
    lots = int(action.get("lots") or 0)
    fill = float(action.get("fillPrice") or 0)
    side = str(action.get("side") or "BUY")

    if act.startswith("INITIAL_") or act.startswith("REVERSE_"):
        leg = "REVERSE" if action.get("isReverse") else "MAIN"
        pos = TradePosition(
            user_id=user_id,
            leg_id=leg,
            trading_mode=mode,
            side=side,
            range_level=fill,
            strike=fill,
            tp=float(action.get("tpPrice") or 0) or None,
            lots=lots,
            quantity=lots * int(instrument.lotsize or 1),
            entry_price=fill,
            status="OPEN",
            exchange=instrument.exchange,
            trading_symbol=instrument.tradingsymbol,
            symbol_token=instrument.token,
        )
        tr.create_open_position(db, pos)
    elif act.startswith("EXIT_"):
        leg = "REVERSE" if action.get("isReverse") else "MAIN"
        open_pos = tr.get_open_position_by_leg(db, user_id, leg)
        if open_pos:
            entry = float(open_pos.entry_price or 0)
            qty_lots = int(open_pos.lots or lots)
            pnl = (fill - entry) * qty_lots if open_pos.side == "BUY" else (entry - fill) * qty_lots
            tr.close_position(db, open_pos, exit_price=fill, exit_reason=act, pnl=pnl)


def process_user_tick(db, user_id: int) -> None:
    row = db.scalar(select(StrategySettings).where(StrategySettings.user_id == user_id))
    if not row or not row.algo_running:
        return

    cfg = tr.load_config_dict(db, user_id)
    parsed = parse_strategy_config(cfg)
    if not _in_session(parsed["start_time"], parsed["end_time"]):
        return

    instrument = get_instrument(parsed["market"])
    if not instrument:
        return

    quote = get_quote_by_key(parsed["market"])
    price = float(quote.price if quote else 0)
    runtime = load_runtime(cfg)
    runtime = _ensure_daily_session(cfg, runtime)
    loaded_runtime = copy.deepcopy(runtime)

    cached = _TICK_PRICE.get(user_id)
    today = _session_date()
    if cached and cached[0] == today:
        runtime["prevPrice"] = cached[1]
        runtime["lastPrice"] = cached[2]

    runtime = _maybe_set_reference(db, user_id, cfg, runtime, parsed, instrument)

    if price <= 0:
        price = float(runtime.get("lastPrice") or 0)
    mode = (row.trading_mode or "PAPER").upper()

    # Even without a usable LTP, persist reference / phase so WAIT_BREAKOUT sticks.
    if price <= 0:
        if _runtime_changed(loaded_runtime, runtime):
            cfg["breakout_runtime"] = runtime
            tr.save_strategy_settings(db, user_id, config=cfg)
        return

    prev_runtime = copy.deepcopy(runtime)
    runtime, actions = process_price_tick(cfg, runtime, price)
    _TICK_PRICE[user_id] = (today, float(runtime.get("prevPrice") or price), float(runtime.get("lastPrice") or price))

    live_failed = False
    kept_actions: list[dict[str, Any]] = []

    for act in actions:
        lots = int(act.get("lots") or 0)
        fill = float(act.get("fillPrice") or price)
        if mode == "LIVE" and lots > 0:
            ready, reason = _live_trading_ready(instrument)
            if not ready:
                tr.append_trading_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    leg=str(act.get("side") or "-"),
                    action="LIVE_SKIPPED",
                    symbol=instrument.tradingsymbol,
                    message=reason[:900],
                )
                live_failed = True
                break

            act_name = str(act.get("action") or "")
            if act_name.startswith("EXIT_"):
                tx = "SELL" if act.get("side") == "BUY" else "BUY"
            else:
                tx = str(act.get("side") or "BUY")
            try:
                raw = angel_orders.place_order(
                    exchange=instrument.exchange,
                    tradingsymbol=instrument.tradingsymbol,
                    symboltoken=instrument.token,
                    transaction_type=tx,
                    quantity=lots * int(instrument.lotsize or 1),
                    product_type="CARRYFORWARD",
                    order_type="MARKET",
                    **_angel_order_headers(),
                )
                order_id, ok, broker_msg = _extract_order_ack(raw)
                if not order_id and not ok:
                    raise RuntimeError(broker_msg or "Angel order rejected")
                tr.append_trading_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    leg=str(act.get("side") or "-"),
                    action=f"LIVE_{str(act.get('action') or 'BREAKOUT')}",
                    symbol=instrument.tradingsymbol,
                    quantity=lots * int(instrument.lotsize or 1),
                    entry_price=fill if "EXIT" not in str(act.get("action")) else None,
                    exit_price=fill if "EXIT" in str(act.get("action")) else None,
                    order_id=order_id or None,
                    pnl=float(act.get("realizedPnl") or 0),
                    message=f"{str(act.get('message') or '')} · {broker_msg}"[:900],
                )
            except Exception as exc:  # noqa: BLE001
                tr.append_trading_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    leg=str(act.get("side") or "-"),
                    action="ERROR",
                    symbol=instrument.tradingsymbol,
                    message=f"Live order failed: {exc}"[:900],
                )
                live_failed = True
                break

        kept_actions.append(act)
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=str(act.get("side") or "-"),
            action=str(act.get("action") or "BREAKOUT"),
            symbol=instrument.tradingsymbol,
            quantity=lots * int(instrument.lotsize or 1),
            entry_price=fill if "EXIT" not in str(act.get("action")) else None,
            exit_price=fill if "EXIT" in str(act.get("action")) else None,
            pnl=float(act.get("realizedPnl") or 0),
            message=str(act.get("message") or "")[:900],
        )

    if mode == "LIVE" and live_failed:
        # Roll back trade actions, but keep newly armed reference / WAIT_BREAKOUT state.
        rolled = copy.deepcopy(prev_runtime)
        rolled["phase"] = prev_runtime.get("phase") or loaded_runtime.get("phase")
        rolled["referencePrice"] = prev_runtime.get("referencePrice") or loaded_runtime.get("referencePrice")
        rolled["buyTrigger"] = prev_runtime.get("buyTrigger") or loaded_runtime.get("buyTrigger")
        rolled["sellTrigger"] = prev_runtime.get("sellTrigger") or loaded_runtime.get("sellTrigger")
        rolled["refCandleTime"] = prev_runtime.get("refCandleTime") or loaded_runtime.get("refCandleTime")
        rolled["message"] = prev_runtime.get("message") or loaded_runtime.get("message")
        rolled["lastPrice"] = runtime.get("lastPrice") or prev_runtime.get("lastPrice")
        rolled["prevPrice"] = runtime.get("prevPrice") or prev_runtime.get("prevPrice")
        runtime = rolled
    else:
        for act in kept_actions:
            _sync_position(db, user_id=user_id, instrument=instrument, mode=mode, action=act, mark_price=price)

    # Critical: always persist reference / WAIT_BREAKOUT / lastPrice so the next tick
    # is not stuck in WAIT_REF (old bug: ref set in memory then thrown away).
    if (
        bool(actions)
        or live_failed
        or _runtime_changed(loaded_runtime, runtime)
        or _runtime_changed(prev_runtime, runtime)
    ):
        cfg["breakout_runtime"] = runtime
        tr.save_strategy_settings(db, user_id, config=cfg)


async def _engine_loop() -> None:
    LOG.info("[BreakoutEngine] Strategy 4 breakout engine started")
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
                        LOG.exception("[BreakoutEngine] tick failed user=%s: %s", uid, exc)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("[BreakoutEngine] loop error: %s", exc)
        try:
            await asyncio.wait_for(_STOP.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
    LOG.info("[BreakoutEngine] stopped")


def start_breakout_engine_task() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    _STOP.clear()
    _TASK = asyncio.create_task(_engine_loop())


async def stop_breakout_engine_task() -> None:
    _STOP.set()
    global _TASK
    if _TASK:
        try:
            await asyncio.wait_for(_TASK, timeout=8.0)
        except asyncio.TimeoutError:
            _TASK.cancel()
        _TASK = None


# Back-compat alias for main.py during transition
start_grid_engine_task = start_breakout_engine_task
stop_grid_engine_task = stop_breakout_engine_task
