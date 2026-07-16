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
    default_runtime,
    fresh_grid_runtime,
    grid_order_price,
    load_runtime,
    parse_strategy_config,
    process_price_tick,
    resolve_active_expiry,
    resolve_invert_grid,
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
        order_id, ok, broker_msg = angel_orders.extract_place_ack(raw)
        if not order_id:
            msg = broker_msg[:900] or "Angel placeOrder returned no order id"
            # Treat API-level reject (often insufficient funds) as ORDER_REJECTED
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode=mode,
                leg=level_id,
                action="ORDER_REJECTED",
                symbol=instrument.tradingsymbol,
                quantity=qty,
                status="REJECTED",
                message=msg,
            )
            raise RuntimeError(msg)
        if not ok:
            # Soft API fail with order id still present — confirm via order book.
            pass

        outcome = angel_orders.await_order_terminal(
            order_id=order_id,
            timeout_sec=min(6.0, float(settings.angel_request_timeout_sec or 15.0)),
            poll_interval_sec=0.1,
            cancel_if_unfilled=True,
            **_angel_order_headers(),
        )
        if not outcome.filled:
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode=mode,
                leg=level_id,
                action="ORDER_REJECTED",
                symbol=instrument.tradingsymbol,
                quantity=qty,
                order_id=order_id,
                status=outcome.status,
                message=(
                    f"Broker {outcome.status}: {outcome.message or broker_msg} · "
                    f"LIMIT @ {limit_px:.2f} · LTP {ltp_at_signal:.2f}"
                )[:900],
            )
            return None

        fill_px = float(outcome.average_price or 0) or limit_px
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=level_id,
            action=f"LIVE_{action}",
            symbol=instrument.tradingsymbol,
            quantity=qty,
            entry_price=fill_px if tx == "BUY" else None,
            exit_price=fill_px if tx == "SELL" else None,
            order_id=order_id,
            status="COMPLETE",
            message=(
                f"FILLED @ {fill_px:.2f} · LIMIT {limit_px:.2f} · LTP {ltp_at_signal:.2f} · {outcome.message or broker_msg}"
            )[:900],
        )
        return order_id
    except Exception as exc:  # noqa: BLE001
        tr.append_trading_log(
            db,
            user_id=user_id,
            mode=mode,
            leg=level_id,
            action="ERROR",
            symbol=instrument.tradingsymbol,
            message=(
                f"Live order rejected by Angel/exchange for {instrument.tradingsymbol}: {exc}. "
                "No Active Trade created; runtime rolled back."
            )[:900],
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
    now = datetime.now(timezone.utc)
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
            entry_time=now,
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
    now = datetime.now(timezone.utc)
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
        entry_time=row.entry_time or now,
        exit_price=exit_px,
        exit_time=now,
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
    # If this U level was re-entered earlier (open row exists), close that row directly
    # so entry price/time come from the actual re-entry fill.
    own = tr.get_open_position_by_leg(db, user_id, level_id)
    if own:
        _close_open_leg(
            db,
            user_id=user_id,
            instrument=instrument,
            leg_id=level_id,
            lots=lots,
            exit_px=exit_px,
            exit_reason="EXIT",
        )
        return
    base = tr.get_open_position_by_leg(db, user_id, "BASE")
    # Entry must be the actual BASE fill price (the lots sold at U levels came from BASE),
    # not the runtime weighted average across D adds.
    base_entry = float(base.entry_price or 0) if base else 0.0
    if base_entry > 0:
        entry_px = base_entry
    qty = lots * instrument.lotsize
    pnl = _position_pnl(entry_px, exit_px, qty)
    now = datetime.now(timezone.utc)
    entry_time = (base.entry_time if base and base.entry_time else now)
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
            entry_time=entry_time,
            exit_price=exit_px,
            exit_time=now,
            exit_reason="EXIT",
            pnl=pnl,
            status="CLOSED",
            exchange=instrument.exchange,
            trading_symbol=instrument.tradingsymbol,
            symbol_token=instrument.token,
        )
    )
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


def manual_close_position(db, user_id: int, leg_id: str) -> None:
    """Close one open grid leg from the dashboard Close button.

    PAPER: closes the DB row at current market price.
    LIVE: places a broker MARKET SELL first and only closes after the fill confirms.
    Grid runtime is synced so the engine does not treat the lots as still open.
    """
    lid = (leg_id or "").strip().upper()
    pos = tr.get_open_position_by_leg(db, user_id, lid)
    if not pos:
        raise ValueError("NO_OPEN_POSITION")

    cfg = tr.load_config_dict(db, user_id)
    parsed = parse_strategy_config(cfg, as_of=_ist_now())
    quote = get_quote_by_key(parsed["market"])
    mark = float(quote.price if quote and quote.price > 0 else 0)
    if mark <= 0:
        mark = float(load_runtime(cfg).get("lastPrice") or 0)
    entry = float(pos.entry_price or 0)
    if mark <= 0:
        mark = entry
    qty = int(pos.quantity or 0)
    lots = int(pos.lots or 0)
    mode = (pos.trading_mode or "PAPER").upper()
    exit_px = round(mark, 2) if mark > 0 else entry

    if mode == "LIVE":
        if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
            raise ValueError("Angel One not configured — cannot close LIVE trade at broker")
        if not pos.trading_symbol or not pos.symbol_token or qty <= 0:
            raise ValueError("Position has no broker symbol/token — cannot close at broker")
        try:
            raw = angel_orders.place_order(
                exchange=(pos.exchange or "MCX").upper(),
                tradingsymbol=pos.trading_symbol,
                symboltoken=str(pos.symbol_token),
                transaction_type="SELL",
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
                message=f"Manual close SELL FILLED @ {exit_px:.2f}"[:900],
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

    pnl = _position_pnl(entry, exit_px, qty)
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
        message=f"Manual close {lots} lot(s) @ {exit_px:.2f}"[:900],
    )

    # Sync grid runtime so the engine does not still count these lots.
    runtime = load_runtime(cfg)
    position = int(runtime.get("positionLots") or 0)
    avg_entry = float(runtime.get("avgEntryPrice") or 0)
    realized = float(runtime.get("realizedPnl") or 0)
    closed_lots = min(lots, position) if position > 0 else 0
    if closed_lots > 0:
        realized += (exit_px - (avg_entry if avg_entry > 0 else entry)) * closed_lots
        position -= closed_lots

    remaining_open = tr.list_open_positions(db, user_id)
    if position <= 0 or not remaining_open:
        # Fully flat — re-arm a clean grid and stop the algo so it cannot instantly re-enter.
        fresh = fresh_grid_runtime(mark)
        fresh["realizedPnl"] = round(realized, 2)
        ref = float(runtime.get("sessionReferencePrice") or 0)
        if ref > 0:
            fresh["sessionReferencePrice"] = ref
        runtime = fresh
        row = db.scalar(select(StrategySettings).where(StrategySettings.user_id == user_id))
        if row and bool(row.algo_running):
            tr.save_strategy_settings(db, user_id, algo_running=False)
            tr.append_trading_log(
                db,
                user_id=user_id,
                mode=mode,
                leg="-",
                action="ALGO_STOPPED",
                message="Algo stopped after manual close (position flat)",
            )
    else:
        runtime["positionLots"] = position
        runtime["realizedPnl"] = round(realized, 2)
        states = dict(runtime.get("levelStates") or {})
        if lid.startswith("D") or lid.startswith("U"):
            states[lid] = "neutral"
        runtime["levelStates"] = states
        if lid == "BASE":
            runtime["baseEntered"] = position > 0

    latest = tr.load_config_dict(db, user_id)
    latest["grid_runtime"] = runtime
    tr.save_strategy_settings(db, user_id, config=latest)


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
    now = _ist_now()
    effective_invert = resolve_invert_grid(cfg, as_of=now)
    tick_cfg = {**cfg, "invertGrid": effective_invert}
    parsed = parse_strategy_config(tick_cfg, as_of=now)
    if parsed["reference_price"] <= 0 or parsed["grid_gap"] <= 0:
        return

    if not _in_session(parsed["start_time"], parsed["end_time"]):
        return

    active_expiry = resolve_active_expiry(cfg, as_of=now)
    instrument = get_instrument(parsed["market"], expiry_iso=active_expiry or None)
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
    prev_invert = runtime.get("effectiveInvertGrid")
    # Do not wipe an open grid when month/invert flips — keep current mode until flat/restart.
    if prev_invert is not None and bool(prev_invert) != effective_invert:
        if int(runtime.get("positionLots") or 0) > 0 or bool(runtime.get("baseEntered")):
            effective_invert = bool(prev_invert)
            tick_cfg = {**cfg, "invertGrid": effective_invert}
        else:
            frozen_ref = float(runtime.get("sessionReferencePrice") or parsed["reference_price"] or 0)
            runtime = default_runtime()
            if frozen_ref > 0:
                runtime["sessionReferencePrice"] = frozen_ref
    runtime["effectiveInvertGrid"] = effective_invert
    in_trade = int(runtime.get("positionLots") or 0) > 0 or bool(runtime.get("baseEntered"))
    if not in_trade and parsed["reference_price"] > 0:
        runtime["sessionReferencePrice"] = parsed["reference_price"]
    elif float(runtime.get("sessionReferencePrice") or 0) <= 0 and parsed["reference_price"] > 0:
        runtime["sessionReferencePrice"] = parsed["reference_price"]
    runtime = seed_runtime_market_price(runtime, price)
    prev_runtime = copy.deepcopy(runtime)
    runtime, actions = process_price_tick({**tick_cfg, "grid_runtime": runtime}, runtime, price)

    kept_actions: list[dict[str, Any]] = []
    live_failed = False

    for act in actions:
        lots = abs(int(act.get("lotsDelta") or 0))
        level_px = float(act.get("levelPrice") or 0)
        if level_px <= 0:
            continue
        fill_px = grid_order_price(level_px)
        log_msg = str(act.get("message") or "")
        log_msg = f"{log_msg} | Grid {fill_px:.2f} · LTP {price:.2f}"[:900]

        if mode == "LIVE" and lots > 0:
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
        # Log per-fill PnL delta when available (not cumulative runtime total).
        fill_pnl = float(act.get("realizedPnl") or 0)
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
            pnl=fill_pnl,
            message=log_msg,
        )

    if mode == "LIVE" and live_failed:
        runtime = prev_runtime
        kept_actions = []
    else:
        # Persist only runtime — never overwrite settings fields mid-tick (avoids ref race).
        latest = tr.load_config_dict(db, user_id)
        latest["grid_runtime"] = runtime
        tr.save_strategy_settings(db, user_id, config=latest)
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
