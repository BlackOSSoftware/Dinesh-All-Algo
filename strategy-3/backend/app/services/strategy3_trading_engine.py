"""
Background live/paper trading engine for Strategy 3 —
SENSEX Expiry Day ITM Premium Breakout.

Per trade window (e.g. 14:35, 14:45, 14:55):
  1. At window reference-candle close (start + timeframe), read SENSEX close.
  2. Compute ITM CE (floor 100) and ITM PE (ceil 100) strikes, resolve BFO contracts.
  3. Read option premium close, apply premium tier -> buy-stop entry, TP, SL.
  4. Monitor option LTP every tick: LTP >= entry -> BUY (paper or live market order).
  5. After fill: LTP >= TP -> exit TARGET_HIT, LTP <= SL -> exit STOPLOSS_HIT.
  6. At EOD exit time, close open legs at market and cancel pending entries.

Runtime state is persisted in config_json["strategy3_runtime"] so restarts resume.
"""

from __future__ import annotations

import asyncio
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
from app.services.angel_candles import post_get_candle_data
from app.services.angel_quote import post_market_quote
from app.services.bfo_scrip_resolver import resolve_sensex_option
from app.services.breakout_logic import (
    add_minutes_to_hhmm,
    build_trade_windows,
    calc_stop_price,
    calc_target_price,
    evaluate_option_setup,
    nearest_itm_ce_strike,
    nearest_itm_pe_strike,
    parse_config,
    parse_hhmm,
    validate_expiry_session_premium,
)
from app.services.sensex_expiry import get_expiry_info, is_sensex_expiry_date
from app.services.sensex_quote import fetch_sensex_live_quote, settings_parsed_tokens

LOG = logging.getLogger(__name__)

_TASK: asyncio.Task | None = None
_STOP = asyncio.Event()

# In-memory last SENSEX LTP per process (avoids a DB write every tick).
_LAST_SENSEX: dict[str, Any] = {"date": "", "price": 0.0, "at": 0.0}

_TICK_INTERVAL_SEC = 0.7
MARKET_OPEN_MIN = 9 * 60 + 15
MARKET_CLOSE_MIN = 15 * 60 + 30
# Square off a little before close so live MARKET orders fill reliably.
EOD_EXIT_HHMM = "15:25"


def _ist_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except ZoneInfoNotFoundError:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _session_date() -> str:
    return _ist_now().strftime("%Y-%m-%d")


def _hhmm_to_minutes(hhmm: str) -> int:
    hh, mm = parse_hhmm(hhmm)
    return hh * 60 + mm


def _now_seconds_of_day() -> float:
    now = _ist_now()
    return now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6


def _angel_headers() -> dict[str, str]:
    return {
        "api_key": settings.angel_api_key.strip(),
        "jwt_token": settings.angel_jwt_token.strip(),
        "source_id": (settings.angel_source_id or "WEB").strip(),
        "client_local_ip": (settings.angel_client_local_ip or "127.0.0.1").strip(),
        "client_public_ip": (settings.angel_client_public_ip or "127.0.0.1").strip(),
        "mac_address": (settings.angel_mac_address or "00:00:00:00:00:00").strip(),
        "user_type": (settings.angel_user_type or "USER").strip(),
    }


def _angel_configured() -> bool:
    return bool(settings.angel_api_key.strip()) and bool(settings.angel_jwt_token.strip())


def fetch_bfo_ltps(tokens: list[str]) -> dict[str, float]:
    """Batch LTP fetch for BFO option tokens -> {token: ltp}."""
    wanted = [str(t).strip() for t in tokens if str(t or "").strip()]
    if not wanted or not _angel_configured():
        return {}
    try:
        raw = post_market_quote(
            mode="LTP",
            exchange_tokens={(settings.angel_option_exchange or "BFO").upper(): wanted},
            timeout_sec=min(float(settings.angel_request_timeout_sec or 5.0), 6.0),
            **_angel_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[S3Engine] BFO quote failed: %s", exc)
        return {}
    data = raw.get("data") if isinstance(raw, dict) else None
    fetched = data.get("fetched") if isinstance(data, dict) else None
    out: dict[str, float] = {}
    for row in fetched or []:
        if not isinstance(row, dict):
            continue
        token = str(row.get("symbolToken") or row.get("symboltoken") or "").strip()
        try:
            ltp = float(row.get("ltp") or row.get("Ltp") or 0)
        except (TypeError, ValueError):
            ltp = 0.0
        if token and ltp > 0:
            out[token] = ltp
    return out


def _sensex_ltp() -> float:
    try:
        raw = fetch_sensex_live_quote(
            exchange_tokens=settings_parsed_tokens(),
            mode=(settings.angel_quote_mode or "LTP").upper(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[S3Engine] SENSEX quote failed: %s", exc)
        return 0.0
    fetched = raw.get("fetched") if isinstance(raw.get("fetched"), list) else []
    row = fetched[0] if fetched and isinstance(fetched[0], dict) else {}
    if str(raw.get("quote_source") or "") != "live":
        return 0.0
    for key in ("ltp", "Ltp"):
        try:
            val = float(row.get(key) or 0)
            if val > 0:
                return val
        except (TypeError, ValueError):
            continue
    return 0.0


def _last_minute_close_from_history(
    *,
    exchange: str,
    token: str,
    from_hhmm: str,
    to_hhmm: str,
) -> float:
    """Close of the last 1-minute candle strictly before to_hhmm (today, IST)."""
    if not _angel_configured():
        return 0.0
    today = _session_date()
    try:
        raw = post_get_candle_data(
            exchange=exchange.upper(),
            symboltoken=str(token),
            interval="ONE_MINUTE",
            fromdate=f"{today} {from_hhmm}",
            todate=f"{today} {to_hhmm}",
            timeout_sec=min(float(settings.angel_request_timeout_sec or 10.0), 10.0),
            **_angel_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[S3Engine] candle fetch failed %s/%s: %s", exchange, token, exc)
        return 0.0
    rows = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return 0.0
    close = 0.0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        label = str(row[0])
        hhmm = label[11:16] if len(label) >= 16 else ""
        if hhmm and hhmm >= to_hhmm:
            continue
        try:
            close = float(row[4])
        except (TypeError, ValueError):
            continue
    return close


# ---------------------------------------------------------------------------
# Runtime state


def _windows_signature(cfg: dict[str, Any]) -> str:
    return "|".join(
        str(cfg.get(k))
        for k in ("startTime", "windowCount", "windowGapMinutes", "candleTimeframeMinutes")
    )


def fresh_strategy3_runtime(cfg: dict[str, Any], session_date: str) -> dict[str, Any]:
    timeframe = max(1, int(cfg.get("candleTimeframeMinutes") or 10))
    windows = build_trade_windows(
        str(cfg.get("startTime") or "14:35"),
        count=int(cfg.get("windowCount") or 3),
        gap_minutes=int(cfg.get("windowGapMinutes") or 10),
    )
    out_windows: list[dict[str, Any]] = []
    for w in windows:
        legs: dict[str, Any] = {}
        for side in ("CE", "PE"):
            legs[side] = {
                "legId": f"W{w.index + 1}{side}",
                "state": "WAITING",
                "status": "Awaiting reference candle close",
                "strike": 0.0,
                "premiumClose": 0.0,
                "entryPct": None,
                "entryPrice": None,
                "tp": None,
                "sl": None,
                "token": "",
                "symbol": "",
                "lotsize": 0,
            }
        out_windows.append(
            {
                "index": w.index,
                "start": w.start_hhmm,
                "refEnd": add_minutes_to_hhmm(w.start_hhmm, timeframe),
                "refClose": None,
                "legs": legs,
            }
        )
    return {
        "sessionDate": session_date,
        "signature": _windows_signature(cfg),
        "message": "",
        "contractExpiry": "",
        "eodDone": False,
        "windows": out_windows,
    }


def load_strategy3_runtime(cfg_raw: dict[str, Any]) -> dict[str, Any]:
    rt = cfg_raw.get("strategy3_runtime")
    return dict(rt) if isinstance(rt, dict) else {}


def _any_leg_in_state(runtime: dict[str, Any], states: tuple[str, ...]) -> bool:
    for w in runtime.get("windows") or []:
        for leg in (w.get("legs") or {}).values():
            if str(leg.get("state")) in states:
                return True
    return False


def _save_runtime(db, user_id: int, cfg_raw: dict[str, Any], runtime: dict[str, Any]) -> None:
    cfg_raw["strategy3_runtime"] = runtime
    tr.save_strategy_settings(db, user_id, config=cfg_raw)


# ---------------------------------------------------------------------------
# Live order helpers


def _product_type_for(cfg: dict[str, Any] | None) -> str:
    """Angel product type from dashboard setting: MIS → INTRADAY, NRML → CARRYFORWARD."""
    raw = str((cfg or {}).get("productType") or "").strip().upper()
    if raw in ("MIS", "INTRADAY"):
        return "INTRADAY"
    if raw in ("NRML", "CARRYFORWARD"):
        return "CARRYFORWARD"
    return (settings.angel_option_product_type or "INTRADAY").upper()


def _place_live_market(
    *,
    tradingsymbol: str,
    token: str,
    transaction_type: str,
    quantity: int,
    product_type: str | None = None,
) -> tuple[bool, float, str, str]:
    """Place LIVE market order and await fill. Returns (filled, avg_price, order_id, message)."""
    try:
        raw = angel_orders.place_market_order(
            exchange=(settings.angel_option_exchange or "BFO").upper(),
            tradingsymbol=tradingsymbol,
            symboltoken=str(token),
            transaction_type=transaction_type.upper(),
            quantity=int(quantity),
            product_type=(product_type or settings.angel_option_product_type or "INTRADAY").upper(),
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
            **_angel_headers(),
        )
        order_id, _ok, broker_msg = angel_orders.extract_place_ack(raw)
        if not order_id:
            return False, 0.0, "", broker_msg or "Angel placeOrder returned no order id"
        outcome = angel_orders.await_order_terminal(
            order_id=order_id,
            timeout_sec=min(8.0, float(settings.angel_request_timeout_sec or 15.0)),
            poll_interval_sec=0.1,
            cancel_if_unfilled=True,
            **_angel_headers(),
        )
        if not outcome.filled:
            return False, 0.0, order_id, f"Broker {outcome.status}: {outcome.message or broker_msg}"
        return True, float(outcome.average_price or 0.0), order_id, outcome.message or "FILLED"
    except Exception as exc:  # noqa: BLE001
        return False, 0.0, "", str(exc)


# ---------------------------------------------------------------------------
# Window arming (reference close -> strikes -> premium -> entry levels)


def _arm_window(
    db,
    *,
    user_id: int,
    mode: str,
    cfg: dict[str, Any],
    runtime: dict[str, Any],
    window: dict[str, Any],
    ref_close: float,
) -> None:
    window["refClose"] = round(ref_close, 2)
    target_pct = float(cfg.get("targetPercent") or 25.0)
    stop_pct = float(cfg.get("stopLossPercent") or 30.0)
    expiry = str(runtime.get("contractExpiry") or "") or None

    tr.append_trading_log(
        db,
        user_id=user_id,
        mode=mode,
        leg=f"W{int(window.get('index') or 0) + 1}",
        action="REFERENCE",
        message=(
            f"Window {window.get('start')} reference close {ref_close:.2f} "
            f"(candle {window.get('start')}–{window.get('refEnd')})"
        ),
    )

    strikes = {
        "CE": nearest_itm_ce_strike(ref_close),
        "PE": nearest_itm_pe_strike(ref_close),
    }

    # Sequential mode: skip this window entirely if a prior trade is still open.
    if str(cfg.get("windowExecutionMode") or "independent") == "sequential" and tr.list_open_positions(db, user_id):
        for side in ("CE", "PE"):
            leg = window["legs"][side]
            leg["state"] = "SKIPPED"
            leg["status"] = "Skipped — prior trade still open (sequential mode)"
            leg["strike"] = strikes[side]
        return

    # Resolve both contracts, then batch one LTP call for premium close.
    resolved: dict[str, Any] = {}
    for side in ("CE", "PE"):
        leg = window["legs"][side]
        leg["strike"] = strikes[side]
        opt = resolve_sensex_option(strikes[side], side, expiry_date=expiry)
        if opt is None:
            leg["state"] = "SKIPPED"
            leg["status"] = f"Option contract not found (strike {strikes[side]:.0f} {side})"
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="SKIPPED",
                strike=strikes[side], message=leg["status"],
            )
            continue
        leg["token"] = opt.token
        leg["symbol"] = opt.tradingsymbol
        leg["lotsize"] = int(opt.lotsize or settings.default_sensex_option_lot_size or 20)
        resolved[side] = opt

    ltps = fetch_bfo_ltps([resolved[s].token for s in resolved])

    # If arming late (engine started after candle close), premium close comes from history.
    late = _now_seconds_of_day() > _hhmm_to_minutes(str(window["refEnd"])) * 60 + 90

    for side, opt in resolved.items():
        leg = window["legs"][side]
        premium = 0.0
        if late:
            premium = _last_minute_close_from_history(
                exchange=(settings.angel_option_exchange or "BFO"),
                token=opt.token,
                from_hhmm=str(window["start"]),
                to_hhmm=str(window["refEnd"]),
            )
        if premium <= 0:
            premium = float(ltps.get(opt.token) or 0.0)
        if premium <= 0:
            leg["state"] = "SKIPPED"
            leg["status"] = "Option premium unavailable at reference close"
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="SKIPPED",
                symbol=opt.tradingsymbol, strike=leg["strike"], message=leg["status"],
            )
            continue

        err = validate_expiry_session_premium(side, leg["strike"], ref_close, premium, cfg=cfg)
        if err:
            leg["state"] = "SKIPPED"
            leg["status"] = err
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="SKIPPED",
                symbol=opt.tradingsymbol, strike=leg["strike"], message=err,
            )
            continue

        setup = evaluate_option_setup(
            side=side,  # type: ignore[arg-type]
            strike=leg["strike"],
            premium_close=premium,
            target_pct=target_pct,
            stop_pct=stop_pct,
            cfg=cfg,
        )
        leg["premiumClose"] = round(premium, 2)
        if not setup.tradable or setup.entry_price is None:
            leg["state"] = "SKIPPED"
            leg["status"] = setup.skip_reason or "Not tradable"
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="SKIPPED",
                symbol=opt.tradingsymbol, strike=leg["strike"],
                message=f"{leg['status']} (premium {premium:.2f})",
            )
            continue

        if tr.leg_has_entry_today_ist(db, user_id, leg["legId"]):
            leg["state"] = "DONE"
            leg["status"] = "Already traded today"
            continue

        leg["entryPct"] = setup.entry_pct
        leg["entryPrice"] = setup.entry_price
        leg["tp"] = setup.target_price
        leg["sl"] = setup.stop_price
        leg["state"] = "ARMED"
        leg["status"] = (
            f"Armed · Entry {setup.entry_price:.2f} · TP {setup.target_price:.2f} · SL {setup.stop_price:.2f}"
        )
        tr.append_trading_log(
            db, user_id=user_id, mode=mode, leg=leg["legId"], action="ARMED",
            symbol=opt.tradingsymbol, strike=leg["strike"],
            entry_price=setup.entry_price,
            message=(
                f"{opt.tradingsymbol} premium close {premium:.2f} → buy-stop {setup.entry_price:.2f} "
                f"(+{(setup.entry_pct or 0) * 100:.0f}%) · TP {setup.target_price:.2f} · SL {setup.stop_price:.2f}"
            ),
        )


# ---------------------------------------------------------------------------
# Entry / exit execution


def _enter_leg(
    db,
    *,
    user_id: int,
    mode: str,
    cfg: dict[str, Any],
    window: dict[str, Any],
    leg: dict[str, Any],
    ltp: float,
) -> None:
    lots = max(1, int(cfg.get("quantity") or 1))
    lotsize = max(1, int(leg.get("lotsize") or settings.default_sensex_option_lot_size or 20))
    qty = lots * lotsize
    fill = ltp
    order_id = ""

    if mode == "LIVE":
        if not _angel_configured():
            leg["state"] = "FAILED"
            leg["status"] = "Angel One not configured — LIVE entry skipped"
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="LIVE_SKIPPED",
                symbol=leg.get("symbol"), message=leg["status"],
            )
            return
        filled, avg, order_id, msg = _place_live_market(
            tradingsymbol=str(leg.get("symbol") or ""),
            token=str(leg.get("token") or ""),
            transaction_type="BUY",
            quantity=qty,
            product_type=_product_type_for(cfg),
        )
        if not filled:
            leg["state"] = "FAILED"
            leg["status"] = f"Entry order failed: {msg}"[:180]
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="ORDER_REJECTED",
                symbol=leg.get("symbol"), quantity=qty, order_id=order_id or None,
                status="REJECTED", message=f"BUY rejected: {msg}"[:900],
            )
            return
        if avg > 0:
            fill = avg

    # Recalculate TP/SL from the actual fill so gaps/slippage keep the configured
    # target and stop-loss percentages accurate.
    if fill > 0:
        target_pct = float(cfg.get("targetPercent") or 25.0)
        stop_pct = float(cfg.get("stopLossPercent") or 30.0)
        leg["tp"] = calc_target_price(fill, target_pct)
        leg["sl"] = calc_stop_price(fill, stop_pct)

    pos = TradePosition(
        user_id=user_id,
        leg_id=leg["legId"],
        trading_mode=mode,
        side=str(leg.get("legId") or "")[-2:] or "CE",
        range_level=float(window.get("refClose") or 0.0),
        strike=float(leg.get("strike") or 0.0),
        tp=float(leg.get("tp") or 0.0) or None,
        lots=lots,
        quantity=qty,
        sl_mode="auto",
        underlying_at_entry=float(window.get("refClose") or 0.0),
        entry_price=round(fill, 2),
        status="OPEN",
        exchange=(settings.angel_option_exchange or "BFO").upper(),
        trading_symbol=str(leg.get("symbol") or "") or None,
        symbol_token=str(leg.get("token") or "") or None,
        order_id=order_id or None,
    )
    tr.create_open_position(db, pos)
    leg["state"] = "OPEN"
    leg["status"] = f"OPEN @ {fill:.2f} · TP {float(leg.get('tp') or 0):.2f} · SL {float(leg.get('sl') or 0):.2f}"
    tr.append_trading_log(
        db, user_id=user_id, mode=mode, leg=leg["legId"],
        action="LIVE_ENTRY" if mode == "LIVE" else "ENTRY",
        symbol=leg.get("symbol"), strike=float(leg.get("strike") or 0), quantity=qty,
        entry_price=round(fill, 2), order_id=order_id or None,
        status="COMPLETE" if mode == "LIVE" else None,
        message=(
            f"BUY {qty} @ {fill:.2f} (trigger {float(leg.get('entryPrice') or 0):.2f}) · "
            f"TP {float(leg.get('tp') or 0):.2f} · SL {float(leg.get('sl') or 0):.2f}"
        ),
    )


def _exit_leg(
    db,
    *,
    user_id: int,
    mode: str,
    leg: dict[str, Any],
    pos: TradePosition,
    exit_px: float,
    reason: str,
    cfg: dict[str, Any] | None = None,
) -> bool:
    qty = int(pos.quantity or 0)
    entry = float(pos.entry_price or 0)
    order_id = ""

    if mode == "LIVE":
        filled, avg, order_id, msg = _place_live_market(
            tradingsymbol=str(pos.trading_symbol or leg.get("symbol") or ""),
            token=str(pos.symbol_token or leg.get("token") or ""),
            transaction_type="SELL",
            quantity=qty,
            product_type=_product_type_for(cfg),
        )
        if not filled:
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg=leg["legId"], action="ORDER_REJECTED",
                symbol=pos.trading_symbol, quantity=qty, order_id=order_id or None,
                status="REJECTED", message=f"Exit SELL rejected ({reason}): {msg}"[:900],
            )
            return False
        if avg > 0:
            exit_px = avg

    pnl = round((exit_px - entry) * qty, 2)
    tr.close_position(db, pos, exit_price=round(exit_px, 2), exit_reason=reason, pnl=pnl)
    leg["state"] = "DONE"
    leg["status"] = f"{reason} @ {exit_px:.2f} · P&L {pnl:+.2f}"
    tr.append_trading_log(
        db, user_id=user_id, mode=mode, leg=leg["legId"],
        action=f"LIVE_{reason}" if mode == "LIVE" else reason,
        symbol=pos.trading_symbol, quantity=qty,
        entry_price=entry, exit_price=round(exit_px, 2), pnl=pnl,
        order_id=order_id or None, status="COMPLETE" if mode == "LIVE" else None,
        message=f"SELL {qty} @ {exit_px:.2f} ({reason}) · P&L {pnl:+.2f}",
    )
    return True


# ---------------------------------------------------------------------------
# Per-user tick


def process_user_tick(db, user_id: int) -> None:
    row = db.scalar(select(StrategySettings).where(StrategySettings.user_id == user_id))
    if not row or not bool(row.algo_running):
        return

    cfg_raw = tr.load_config_dict(db, user_id)
    cfg = parse_config(cfg_raw)
    mode = (row.trading_mode or "PAPER").upper()
    today = _session_date()

    runtime = load_strategy3_runtime(cfg_raw)
    changed = False
    if (
        str(runtime.get("sessionDate") or "") != today
        or not isinstance(runtime.get("windows"), list)
        or (
            str(runtime.get("signature") or "") != _windows_signature(cfg)
            and not _any_leg_in_state(runtime, ("OPEN",))
        )
    ):
        runtime = fresh_strategy3_runtime(cfg, today)
        changed = True

    now = _ist_now()
    minutes_now = now.hour * 60 + now.minute
    if now.weekday() >= 5 or minutes_now < MARKET_OPEN_MIN or minutes_now > MARKET_CLOSE_MIN:
        if runtime.get("message") != "Market closed":
            runtime["message"] = "Market closed"
            changed = True
        if changed:
            _save_runtime(db, user_id, cfg_raw, runtime)
        return

    if bool(cfg.get("expiryDayOnly", True)) and not is_sensex_expiry_date(today):
        msg = "Not SENSEX expiry day — waiting for expiry session"
        if runtime.get("message") != msg:
            runtime["message"] = msg
            changed = True
            tr.append_trading_log(
                db, user_id=user_id, mode=mode, leg="-", action="WAITING", message=msg,
            )
        if changed:
            _save_runtime(db, user_id, cfg_raw, runtime)
        return

    if not runtime.get("contractExpiry"):
        info = get_expiry_info(today)
        runtime["contractExpiry"] = str(info.get("contractExpiryDate") or "")
        changed = True

    if runtime.get("message"):
        runtime["message"] = ""
        changed = True

    # Track SENSEX LTP in-memory so window boundary crossings use a fresh tick.
    sensex = _sensex_ltp()
    if sensex > 0:
        _LAST_SENSEX.update({"date": today, "price": sensex, "at": time.time()})

    now_sec = _now_seconds_of_day()
    windows: list[dict[str, Any]] = runtime.get("windows") or []

    # 1) Arm windows whose reference candle just closed.
    for window in windows:
        if window.get("refClose") is not None:
            continue
        ref_end_sec = _hhmm_to_minutes(str(window.get("refEnd") or "14:45")) * 60
        if now_sec < ref_end_sec:
            continue
        ref_close = 0.0
        fresh_tick = (
            _LAST_SENSEX.get("date") == today
            and float(_LAST_SENSEX.get("price") or 0) > 0
            and now_sec - ref_end_sec <= 90
        )
        if fresh_tick:
            ref_close = float(_LAST_SENSEX["price"])
        else:
            exch, toks = next(iter(settings_parsed_tokens().items()), ("BSE", ["99919000"]))
            ref_close = _last_minute_close_from_history(
                exchange=exch,
                token=toks[0] if toks else "99919000",
                from_hhmm=str(window.get("start") or "14:35"),
                to_hhmm=str(window.get("refEnd") or "14:45"),
            )
            if ref_close <= 0 and sensex > 0:
                ref_close = sensex
        if ref_close <= 0:
            continue  # retry next tick
        _arm_window(
            db, user_id=user_id, mode=mode, cfg=cfg,
            runtime=runtime, window=window, ref_close=ref_close,
        )
        changed = True

    # 2) Gather tokens for armed/open legs, one batched LTP call.
    tokens: list[str] = []
    for window in windows:
        for leg in (window.get("legs") or {}).values():
            if str(leg.get("state")) in ("ARMED", "OPEN") and leg.get("token"):
                tokens.append(str(leg["token"]))
    ltps = fetch_bfo_ltps(list(dict.fromkeys(tokens))) if tokens else {}

    eod = now_sec >= _hhmm_to_minutes(EOD_EXIT_HHMM) * 60
    one_at_a_time = bool(cfg.get("oneTradeAtATime"))

    # 3) Entries and exits on option LTP.
    for window in windows:
        for leg in (window.get("legs") or {}).values():
            state = str(leg.get("state"))
            ltp = float(ltps.get(str(leg.get("token") or "")) or 0.0)

            if state == "ARMED":
                if eod:
                    leg["state"] = "DONE"
                    leg["status"] = "Entry not triggered before EOD"
                    changed = True
                    continue
                if ltp <= 0:
                    continue
                entry_price = float(leg.get("entryPrice") or 0)
                if entry_price <= 0 or ltp < entry_price:
                    continue
                if one_at_a_time and tr.list_open_positions(db, user_id):
                    continue
                _enter_leg(
                    db, user_id=user_id, mode=mode, cfg=cfg,
                    window=window, leg=leg, ltp=ltp,
                )
                changed = True
                continue

            if state == "OPEN":
                pos = tr.get_open_position_by_leg(db, user_id, str(leg.get("legId") or ""))
                if not pos:
                    leg["state"] = "DONE"
                    leg["status"] = "Closed manually"
                    changed = True
                    continue
                if eod:
                    # LIVE fills at market; PAPER falls back to entry if no tick.
                    px = ltp if ltp > 0 else float(pos.entry_price or 0)
                    if _exit_leg(
                        db, user_id=user_id, mode=mode, leg=leg,
                        pos=pos, exit_px=px, reason="MARKET_CLOSE", cfg=cfg,
                    ):
                        changed = True
                    continue
                if ltp <= 0:
                    continue
                tp = float(leg.get("tp") or pos.tp or 0)
                sl = float(leg.get("sl") or 0)
                if tp > 0 and ltp >= tp:
                    if _exit_leg(
                        db, user_id=user_id, mode=mode, leg=leg,
                        pos=pos, exit_px=ltp, reason="TARGET_HIT", cfg=cfg,
                    ):
                        changed = True
                    continue
                if sl > 0 and ltp <= sl:
                    if _exit_leg(
                        db, user_id=user_id, mode=mode, leg=leg,
                        pos=pos, exit_px=ltp, reason="STOPLOSS_HIT", cfg=cfg,
                    ):
                        changed = True

    if eod and not runtime.get("eodDone"):
        runtime["eodDone"] = True
        changed = True

    if changed:
        _save_runtime(db, user_id, cfg_raw, runtime)


def _tick_all_users() -> None:
    db = SessionLocal()
    try:
        users = db.scalars(
            select(StrategySettings.user_id).where(StrategySettings.algo_running.is_(True))
        ).all()
        for uid in users:
            try:
                process_user_tick(db, int(uid))
            except Exception as exc:  # noqa: BLE001
                LOG.exception("[S3Engine] tick failed user=%s: %s", uid, exc)
    finally:
        db.close()


async def _engine_loop() -> None:
    LOG.info("[S3Engine] Strategy 3 breakout engine started")
    while not _STOP.is_set():
        try:
            # Quote/order calls are blocking urllib; keep the API event loop responsive.
            await asyncio.to_thread(_tick_all_users)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("[S3Engine] loop error: %s", exc)
        try:
            await asyncio.wait_for(_STOP.wait(), timeout=_TICK_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass
    LOG.info("[S3Engine] stopped")


def start_strategy3_engine_task() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    _STOP.clear()
    _TASK = asyncio.create_task(_engine_loop())


async def stop_strategy3_engine_task() -> None:
    _STOP.set()
    global _TASK
    if _TASK:
        try:
            await asyncio.wait_for(_TASK, timeout=8.0)
        except asyncio.TimeoutError:
            _TASK.cancel()
        _TASK = None
