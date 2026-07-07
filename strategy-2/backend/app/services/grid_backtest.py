"""Strategy 2 MCX grid backtest on Angel historical candles."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.services.angel_candles import post_get_candle_data
from app.services.grid_backtest_candles import process_backtest_candle
from app.services.grid_logic import (
    bootstrap_initial_entry,
    build_grid_levels,
    default_runtime,
    parse_strategy_config,
    validate_grid_trade_sequence,
)
from app.services.mcx_instruments import get_instrument

LOG = logging.getLogger(__name__)

MAX_BACKTEST_DAYS = 31
FETCH_RETRIES = 3
FETCH_RETRY_DELAY_SEC = 1.5


def _ist_tz():
    try:
        return ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = (value or "09:15").strip().split(":")
    h = int(parts[0]) if parts and parts[0].isdigit() else 9
    m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 15
    return h, m


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value.strip()[:10], "%Y-%m-%d")


def _iter_dates(from_date: str, to_date: str) -> list[str]:
    start = _parse_date(from_date)
    end = _parse_date(to_date)
    if end < start:
        raise ValueError("to_date must be on or after from_date")
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _parse_candle_row(row: Any) -> tuple[str | None, float | None, float | None, float | None, float | None]:
    if isinstance(row, (list, tuple)) and len(row) >= 5:
        dt = str(row[0]) if row[0] is not None else None
        try:
            return dt, float(row[1]), float(row[2]), float(row[3]), float(row[4])
        except (TypeError, ValueError):
            return dt, None, None, None, None
    if isinstance(row, dict):
        dt_raw = row.get("date") or row.get("datetime") or row.get("DateTime")
        dt = str(dt_raw) if dt_raw is not None else None

        def _f(*keys: str) -> float | None:
            for k in keys:
                v = row.get(k)
                if v is None or v == "":
                    continue
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
            return None

        return dt, _f("open", "Open"), _f("high", "High"), _f("low", "Low"), _f("close", "Close")
    return None, None, None, None, None


def _fetch_day_candles(
    *,
    date: str,
    start_time: str,
    end_time: str,
    exchange: str,
    symboltoken: str,
) -> list[dict[str, Any]]:
    yy, mo, dd = int(date[0:4]), int(date[5:7]), int(date[8:10])
    sh, sm = _parse_hhmm(start_time)
    eh, em = _parse_hhmm(end_time)
    tz = _ist_tz()
    from_dt = datetime(yy, mo, dd, sh, sm, 0, tzinfo=tz)
    to_dt = datetime(yy, mo, dd, eh, em, 0, tzinfo=tz)
    if to_dt <= from_dt:
        return []

    raw = post_get_candle_data(
        api_key=settings.angel_api_key.strip(),
        jwt_token=settings.angel_jwt_token.strip(),
        source_id=settings.angel_source_id,
        client_local_ip=settings.angel_client_local_ip,
        client_public_ip=settings.angel_client_public_ip,
        mac_address=settings.angel_mac_address,
        user_type=settings.angel_user_type,
        exchange=exchange,
        symboltoken=symboltoken,
        interval="ONE_MINUTE",
        fromdate=from_dt.strftime("%Y-%m-%d %H:%M"),
        todate=to_dt.strftime("%Y-%m-%d %H:%M"),
        timeout_sec=float(settings.angel_request_timeout_sec or 20.0),
    )
    rows = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), list) else []
    candles: list[dict[str, Any]] = []
    for row in rows:
        ct, o, h, l, c = _parse_candle_row(row)
        if ct is None or o is None or h is None or l is None or c is None:
            continue
        candles.append({"time": ct, "open": o, "high": h, "low": l, "close": c})
    return candles


def _config_from_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "startTime": params.get("startTime") or "09:15",
        "endTime": params.get("endTime") or "23:30",
        "market": params.get("market") or "CRUDE_OIL",
        "referencePrice": params.get("referencePrice") or 0,
        "initialLots": params.get("initialLots") or 0,
        "gridGap": params.get("gridGap") or 0,
        "gridLevelsAbove": params.get("gridLevelsAbove") or 0,
        "gridLevelsBelow": params.get("gridLevelsBelow") or 0,
        "lotsPerGrid": params.get("lotsPerGrid") or 0,
        "invertGrid": params.get("invertGrid") or False,
    }


def run_grid_backtest(params: dict[str, Any]) -> dict[str, Any]:
    cfg = _config_from_params(params)
    parsed = parse_strategy_config(cfg)
    if parsed["reference_price"] <= 0 or parsed["grid_gap"] <= 0:
        raise ValueError("Reference price and grid gap must be greater than zero")
    if parsed["initial_lots"] <= 0:
        raise ValueError("Initial lots must be greater than zero")

    from_date = str(params.get("fromDate") or "")[:10]
    to_date = str(params.get("toDate") or "")[:10]
    if not from_date or not to_date:
        raise ValueError("fromDate and toDate are required")

    dates = _iter_dates(from_date, to_date)
    if len(dates) > MAX_BACKTEST_DAYS:
        raise ValueError(f"Maximum {MAX_BACKTEST_DAYS} days per backtest")

    instrument = get_instrument(parsed["market"])
    if not instrument or not instrument.configured:
        raise ValueError("MCX instrument not configured — check Angel login / MCX tokens")

    if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
        raise ValueError("Angel One JWT not configured")

    levels = build_grid_levels(
        reference_price=parsed["reference_price"],
        grid_gap=parsed["grid_gap"],
        levels_above=parsed["grid_levels_above"],
        levels_below=parsed["grid_levels_below"],
        initial_lots=parsed["initial_lots"],
        lots_per_grid=parsed["lots_per_grid"],
        invert_grid=parsed["invert_grid"],
    )

    runtime = default_runtime()
    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    all_candles: list[dict[str, Any]] = []
    day_summaries: list[dict[str, Any]] = []
    trade_id = 1
    event_id = 1
    days_run = 0
    skipped_days = 0
    skipped_dates: list[str] = []
    max_lots = 0
    bootstrapped = False

    def _fetch_one(date: str) -> tuple[str, list[dict[str, Any]]]:
        last_exc: Exception | None = None
        for attempt in range(FETCH_RETRIES):
            try:
                candles = _fetch_day_candles(
                    date=date,
                    start_time=parsed["start_time"],
                    end_time=parsed["end_time"],
                    exchange=instrument.exchange,
                    symboltoken=instrument.token,
                )
                if candles:
                    return date, candles
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                LOG.warning(
                    "Backtest candle fetch failed %s (attempt %s/%s): %s",
                    date,
                    attempt + 1,
                    FETCH_RETRIES,
                    exc,
                )
            if attempt + 1 < FETCH_RETRIES:
                time.sleep(FETCH_RETRY_DELAY_SEC)
        if last_exc:
            LOG.warning("Backtest giving up on %s after %s attempts", date, FETCH_RETRIES)
        return date, []

    workers = min(8, max(1, len(dates)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        day_results = list(pool.map(_fetch_one, dates))

    for date, day_candles in day_results:
        if not day_candles:
            skipped_days += 1
            skipped_dates.append(date)
            continue

        days_run += 1
        day_start_pnl = float(runtime.get("realizedPnl") or 0)
        day_start_trades = len(trades)
        day_open = True

        for candle in day_candles:
            o, c = candle["open"], candle["close"]
            time_str = str(candle["time"])
            all_candles.append({**candle, "date": date})

            if not bootstrapped:
                runtime, boot_acts = bootstrap_initial_entry(
                    cfg,
                    runtime,
                    fill_price=parsed["reference_price"],
                )
                for act in boot_acts:
                    events.append({**act, "id": event_id, "date": date, "time": time_str})
                    event_id += 1
                    trades.append(_trade_row(trade_id, date, time_str, act, instrument.tradingsymbol))
                    trade_id += 1
                bootstrapped = True
                max_lots = max(max_lots, int(runtime.get("positionLots") or 0))

            skip_open = day_open
            if day_open:
                day_open = False

            runtime, actions = process_backtest_candle(
                cfg,
                runtime,
                open_price=float(o),
                close_price=float(c),
                high_price=float(candle.get("high") or 0),
                low_price=float(candle.get("low") or 0),
                skip_open_segment=skip_open,
            )
            for act in actions:
                events.append({**act, "id": event_id, "date": date, "time": time_str})
                event_id += 1
                trades.append(_trade_row(trade_id, date, time_str, act, instrument.tradingsymbol))
                trade_id += 1

            max_lots = max(max_lots, int(runtime.get("positionLots") or 0))

        day_pnl = float(runtime.get("realizedPnl") or 0) - day_start_pnl
        day_summaries.append(
            {
                "date": date,
                "trades": len(trades) - day_start_trades,
                "pnl": round(day_pnl, 2),
                "endPositionLots": int(runtime.get("positionLots") or 0),
                "candles": len(day_candles),
            }
        )

    total_pnl = float(runtime.get("realizedPnl") or 0)
    wins = sum(1 for d in day_summaries if d["pnl"] > 0)
    losses = sum(1 for d in day_summaries if d["pnl"] < 0)

    seq_errors = validate_grid_trade_sequence(
        trades,
        max_upper=parsed["grid_levels_above"],
        max_lower=parsed["grid_levels_below"],
    )
    if seq_errors:
        LOG.warning("Grid sequence validation: %s", "; ".join(seq_errors[:5]))

    chart_candles = all_candles
    chart_trades = trades
    subtitle = (
        f"{len(all_candles)} x 1-min OHLC candles · open→high/low→close · "
        f"max 1 action/level/candle · {days_run} days"
    )
    if skipped_dates:
        subtitle += f" · skipped: {', '.join(skipped_dates)}"

    return {
        "ok": days_run > 0,
        "message": "" if days_run > 0 else "No candle data for selected range",
        "instrument": instrument.tradingsymbol,
        "market": parsed["market"],
        "fromDate": from_date,
        "toDate": to_date,
        "daysRun": days_run,
        "skippedDays": skipped_days,
        "skippedDates": skipped_dates,
        "summary": {
            "totalTrades": len(trades),
            "totalPnl": round(total_pnl, 2),
            "finalPositionLots": int(runtime.get("positionLots") or 0),
            "maxLots": max_lots,
            "winDays": wins,
            "lossDays": losses,
            "netDays": len(day_summaries),
        },
        "gridLevels": [
            {"level": l.level_id, "price": l.price, "action": l.action_label} for l in levels
        ],
        "daySummaries": day_summaries,
        "trades": trades,
        "events": events,
        "candles": chart_candles,
        "chartTrades": chart_trades,
        "chartSubtitle": subtitle,
        "referencePrice": parsed["reference_price"],
    }


def _trade_row(trade_id: int, date: str, time_str: str, act: dict[str, Any], symbol: str) -> dict[str, Any]:
    delta = int(act.get("lotsDelta") or 0)
    fill = float(act.get("fillPrice") or act.get("price") or 0)
    level_px = float(act.get("levelPrice") or 0)
    is_buy = delta > 0
    return {
        "id": trade_id,
        "date": date,
        "time": time_str.replace("T", " "),
        "action": str(act.get("action") or ""),
        "level": str(act.get("level") or ""),
        "lotsDelta": delta,
        "side": "BUY" if is_buy else "SELL",
        "lots": abs(delta),
        "levelPrice": level_px,
        "fillPrice": fill,
        "price": fill,
        "entryPrice": fill if is_buy else None,
        "exitPrice": fill if not is_buy else None,
        "gridEntryPrice": level_px if is_buy else None,
        "gridExitPrice": level_px if not is_buy else None,
        "positionAfter": int(act.get("positionAfter") or 0),
        "realizedPnl": float(act.get("realizedPnl") or 0),
        "message": str(act.get("message") or ""),
        "symbol": symbol,
    }
