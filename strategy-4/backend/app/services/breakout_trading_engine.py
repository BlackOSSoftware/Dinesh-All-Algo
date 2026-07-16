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
    align_runtime_to_config,
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
    # Stale lock from another instrument (e.g. NG ref while Crude selected) must refetch.
    if _num(runtime.get("referencePrice")) > 0:
        rt_market = str(runtime.get("market") or "").upper()
        want_market = str(parsed.get("market") or "").upper()
        if (not rt_market or not want_market or rt_market == want_market) and str(
            runtime.get("phase") or ""
        ) not in ("WAIT_REF", "IDLE"):
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

    key = f"{user_id}:{_session_date()}:{parsed['market']}"
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
            close = _num(ref.get("close"))
            quote_px = 0.0
            try:
                q = get_quote_by_key(parsed["market"])
                quote_px = float(q.price if q else 0)
            except Exception:  # noqa: BLE001
                quote_px = 0.0
            from app.services.breakout_logic import _reference_matches_ltp

            if quote_px > 0 and close > 0 and not _reference_matches_ltp(close, quote_px):
                rt = copy.copy(runtime)
                rt["phase"] = "WAIT_REF"
                rt["message"] = (
                    f"Ignored bad reference close {close:.2f} for {instrument.tradingsymbol} "
                    f"(LTP {quote_px:.2f}) — retrying"
                )
                return rt
            rt = set_reference_from_candle(runtime, ref, parsed)
            rt["refSymbol"] = instrument.tradingsymbol
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode="PAPER",
                leg="REF",
                action="REFERENCE_SET",
                symbol=instrument.tradingsymbol,
                entry_price=close,
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
            put_sl_pts=int(float(action.get("slPrice") or 0) or 0) or None,
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
            # Rupee PnL: use full quantity (lots × lotsize), matching active-trade PnL.
            qty = int(open_pos.quantity or 0) or int(open_pos.lots or lots) * int(instrument.lotsize or 1)
            pnl = (fill - entry) * qty if open_pos.side == "BUY" else (entry - fill) * qty
            tr.close_position(db, open_pos, exit_price=fill, exit_reason=act, pnl=pnl)


def manual_close_position(db, user_id: int, leg_id: str) -> None:
    """Close an open breakout leg from the dashboard Close button.

    PAPER: closes the DB row at current market price.
    LIVE: places the opposite MARKET order at the broker and waits for fill confirmation.
    Breakout runtime is marked DONE so the engine does not keep trading the closed leg.
    """
    lid = (leg_id or "").strip().upper()
    pos = tr.get_open_position_by_leg(db, user_id, lid)
    if not pos:
        raise ValueError("NO_OPEN_POSITION")

    cfg = tr.load_config_dict(db, user_id)
    parsed = parse_strategy_config(cfg)
    quote = get_quote_by_key(parsed["market"])
    mark = float(quote.price if quote and quote.price > 0 else 0)
    runtime = load_runtime(cfg)
    if mark <= 0:
        mark = _num(runtime.get("lastPrice"))
    entry = float(pos.entry_price or 0)
    if mark <= 0:
        mark = entry
    qty = int(pos.quantity or 0)
    lots = int(pos.lots or 0)
    side = (pos.side or "BUY").upper()
    mode = (pos.trading_mode or "PAPER").upper()
    exit_px = round(mark, 2) if mark > 0 else entry

    if mode == "LIVE":
        if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
            raise ValueError("Angel One not configured — cannot close LIVE trade at broker")
        if not pos.trading_symbol or not pos.symbol_token or qty <= 0:
            raise ValueError("Position has no broker symbol/token — cannot close at broker")
        tx = "SELL" if side == "BUY" else "BUY"
        try:
            raw = angel_orders.place_order(
                exchange=(pos.exchange or "MCX").upper(),
                tradingsymbol=pos.trading_symbol,
                symboltoken=str(pos.symbol_token),
                transaction_type=tx,
                quantity=qty,
                product_type="CARRYFORWARD",
                order_type="MARKET",
                timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
                **_angel_order_headers(),
            )
            order_id, _ok, broker_msg = angel_orders.extract_place_ack(raw)
            if not order_id:
                raise RuntimeError(broker_msg or "Angel placeOrder returned no order id")
            outcome = angel_orders.await_order_terminal(
                order_id=order_id,
                timeout_sec=min(8.0, float(settings.angel_request_timeout_sec or 15.0)),
                poll_interval_sec=0.1,
                cancel_if_unfilled=True,
                **_angel_order_headers(),
            )
            if not outcome.filled:
                raise RuntimeError(f"Broker {outcome.status}: {outcome.message or broker_msg}")
            exit_px = float(outcome.average_price or 0) or exit_px
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode=mode,
                leg=lid,
                action="LIVE_MANUAL_CLOSE",
                symbol=pos.trading_symbol,
                quantity=qty,
                exit_price=exit_px,
                order_id=order_id,
                status="COMPLETE",
                message=f"Manual close {tx} FILLED @ {exit_px:.2f}"[:900],
            )
        except Exception as exc:  # noqa: BLE001
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode=mode,
                leg=lid,
                action="ERROR",
                symbol=pos.trading_symbol,
                quantity=qty,
                message=f"Manual close rejected by broker: {exc}"[:900],
            )
            raise ValueError(f"Broker close failed: {exc}") from exc

    pnl = (exit_px - entry) * qty if side == "BUY" else (entry - exit_px) * qty
    if entry <= 0:
        pnl = 0.0
    tr.close_position(db, pos, exit_price=exit_px, exit_reason="MANUAL_CLOSE", pnl=pnl)
    tr.append_trading_log(
        db,
        user_id=user_id,
        mode=mode,
        leg=lid,
        action="MANUAL_CLOSE",
        symbol=pos.trading_symbol,
        quantity=qty,
        entry_price=entry,
        exit_price=exit_px,
        pnl=pnl,
        message=f"Manual close {side} {lots} lot(s) @ {exit_px:.2f}"[:900],
    )

    # Runtime: realize points-based PnL and finish the day so no phantom TP/SL fires.
    rt_side = str(runtime.get("side") or "")
    if int(runtime.get("positionLots") or 0) > 0 and rt_side in ("BUY", "SELL"):
        rt_entry = _num(runtime.get("entryPrice"))
        rt_lots = int(runtime.get("positionLots") or 0)
        delta = (exit_px - rt_entry) * rt_lots if rt_side == "BUY" else (rt_entry - exit_px) * rt_lots
        runtime["realizedPnl"] = round(_num(runtime.get("realizedPnl")) + delta, 2)
    runtime.update(
        {
            "positionLots": 0,
            "side": None,
            "entryPrice": 0.0,
            "tpPrice": 0.0,
            "slPrice": 0.0,
            "phase": "DONE",
            "message": "Manually closed from dashboard",
        }
    )
    cfg["breakout_runtime"] = runtime
    tr.save_strategy_settings(db, user_id, config=cfg)


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
    runtime = align_runtime_to_config(
        runtime,
        parsed,
        symbol=instrument.tradingsymbol or "",
        last_price=price,
    )[0]
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
                order_id, ok, broker_msg = angel_orders.extract_place_ack(raw)
                if not order_id:
                    raise RuntimeError(broker_msg or "Angel order rejected (no order id)")

                outcome = angel_orders.await_order_terminal(
                    order_id=order_id,
                    timeout_sec=min(5.0, float(settings.angel_request_timeout_sec or 15.0)),
                    poll_interval_sec=0.08,
                    cancel_if_unfilled=True,
                    **_angel_order_headers(),
                )
                if not outcome.filled:
                    tr.append_trading_log(
                        db,
                        user_id=user_id,
                        mode=mode,
                        leg=str(act.get("side") or "-"),
                        action="ORDER_REJECTED",
                        symbol=instrument.tradingsymbol,
                        quantity=lots * int(instrument.lotsize or 1),
                        order_id=order_id,
                        status=outcome.status,
                        message=(f"Broker {outcome.status}: {outcome.message or broker_msg}")[:900],
                    )
                    live_failed = True
                    break

                fill = float(outcome.average_price or 0) or fill
                act["fillPrice"] = fill
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
                    order_id=order_id,
                    status="COMPLETE",
                    pnl=float(act.get("realizedPnl") or 0),
                    message=f"{str(act.get('message') or '')} · FILLED @ {fill:.2f} · {outcome.message or broker_msg}"[:900],
                )
            except Exception as exc:  # noqa: BLE001
                tr.append_trading_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    leg=str(act.get("side") or "-"),
                    action="ORDER_REJECTED",
                    symbol=instrument.tradingsymbol,
                    status="REJECTED",
                    message=f"Live order failed: {exc}"[:900],
                )
                live_failed = True
                break

        kept_actions.append(act)
        if mode != "LIVE":
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
            await asyncio.wait_for(_STOP.wait(), timeout=0.05)
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
