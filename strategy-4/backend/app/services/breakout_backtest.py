"""Strategy 4 MCX breakout backtest on Angel historical 1-min candles."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.services.angel_candles import post_get_candle_data
from app.services.breakout_backtest_stats import compute_backtest_statistics
from app.services.breakout_logic import (
    EXECUTION_POLICY,
    build_strategy_levels,
    format_time_label,
    parse_strategy_config,
    simulate_day,
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

    last_err: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
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
                candles.append({"time": ct, "open": o, "high": h, "low": l, "close": c, "date": date})
            return candles
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt + 1 < FETCH_RETRIES:
                time.sleep(FETCH_RETRY_DELAY_SEC)
    if last_err:
        raise last_err
    return []


def _config_from_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "startTime": params.get("startTime") or "18:29",
        "endTime": params.get("endTime") or "23:30",
        "market": params.get("market") or "CRUDE_OIL",
        "lotSize": params.get("lotSize") or params.get("lots") or 1,
        "breakoutDistance": params.get("breakoutDistance") or 0.5,
        "takeProfit": params.get("takeProfit") or 1.0,
        "stopLoss": params.get("stopLoss") or 0.8,
    }


def _daily_reference_row(report: dict[str, Any], start_time: str) -> dict[str, Any]:
    buy_touch = report.get("buyTriggerFirstTouchTime")
    sell_touch = report.get("sellTriggerFirstTouchTime")
    return {
        "date": report.get("date"),
        "referenceClose": report.get("referenceClose"),
        "referenceOpen": report.get("referenceOpen"),
        "referenceHigh": report.get("referenceHigh"),
        "referenceLow": report.get("referenceLow"),
        "referenceCandleTime": format_time_label(str(report.get("referenceCandleTime") or "")) or start_time,
        "buyTrigger": report.get("buyTrigger"),
        "sellTrigger": report.get("sellTrigger"),
        "buyTriggerTime": format_time_label(str(buy_touch)) if buy_touch else "Not Triggered",
        "sellTriggerTime": format_time_label(str(sell_touch)) if sell_touch else "Not Triggered",
        "buyTriggerTouchHigh": report.get("buyTriggerTouchHigh"),
        "sellTriggerTouchLow": report.get("sellTriggerTouchLow"),
        "firstTriggerSide": report.get("firstTriggerSide") or report.get("initialDirection") or "—",
        "initialDirection": report.get("initialDirection") or "—",
        "initialTriggerTime": format_time_label(str(report.get("initialTriggerTime") or "")) or "—",
        "result": report.get("result") or "—",
        "pnl": report.get("pnl"),
        "phase": report.get("phase"),
        "sameBarNotes": report.get("sameBarNotes") or [],
    }


def _event_row(ev: dict[str, Any], *, event_id: int, symbol: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "date": ev.get("date") or "",
        "time": ev.get("time") or "",
        "action": ev.get("action") or "",
        "side": ev.get("side") or "",
        "lots": int(ev.get("lots") or 0),
        "fillPrice": float(ev.get("fillPrice") or 0),
        "entryPrice": ev.get("entryPrice"),
        "exitPrice": ev.get("exitPrice"),
        "tpPrice": ev.get("tpPrice"),
        "slPrice": ev.get("slPrice"),
        "isReverse": bool(ev.get("isReverse")),
        "entryType": ev.get("entryType"),
        "exitReason": ev.get("exitReason"),
        "tradePnl": ev.get("tradePnl"),
        "runningDayPnl": ev.get("runningDayPnl") or ev.get("realizedPnl"),
        "realizedPnl": float(ev.get("realizedPnl") or 0),
        "message": ev.get("message") or "",
        "symbol": symbol,
        "sameBarAmbiguity": bool(ev.get("sameBarAmbiguity")),
    }


def _round_trip_row(trip: dict[str, Any], *, symbol: str, date: str) -> dict[str, Any]:
    return {
        **trip,
        "date": date,
        "symbol": symbol,
        "entryTimeLabel": format_time_label(str(trip.get("entryTime") or "")),
        "exitTimeLabel": format_time_label(str(trip.get("exitTime") or "")),
    }


def run_breakout_backtest(params: dict[str, Any]) -> dict[str, Any]:
    cfg = _config_from_params(params)
    parsed = parse_strategy_config(cfg)
    if parsed["breakout_distance"] <= 0 or parsed["take_profit"] <= 0 or parsed["stop_loss"] <= 0:
        raise ValueError("Breakout distance, take profit, and stop loss must be greater than zero")
    if parsed["lots"] <= 0:
        raise ValueError("Lot size must be greater than zero")

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

    symbol = instrument.tradingsymbol or parsed["market"]
    exchange = instrument.exchange or "MCX"
    token = instrument.token or ""

    def fetch_one(d: str) -> tuple[str, list[dict[str, Any]]]:
        candles = _fetch_day_candles(
            date=d,
            start_time=parsed["start_time"],
            end_time=parsed["end_time"],
            exchange=exchange,
            symboltoken=token,
        )
        return d, candles

    day_candles: dict[str, list[dict[str, Any]]] = {}
    skipped: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, len(dates))) as pool:
        for d, candles in pool.map(fetch_one, dates):
            if candles:
                day_candles[d] = candles
            else:
                skipped.append(d)

    all_events: list[dict[str, Any]] = []
    all_round_trips: list[dict[str, Any]] = []
    daily_reports: list[dict[str, Any]] = []
    daily_reference: list[dict[str, Any]] = []
    daily_charts: list[dict[str, Any]] = []
    day_summaries: list[dict[str, Any]] = []
    event_id = 0

    for d in dates:
        candles = day_candles.get(d) or []
        if not candles:
            continue
        rt, day_events, report = simulate_day(candles, cfg, session_date=d)
        daily_reports.append(report)
        daily_reference.append(_daily_reference_row(report, parsed["start_time"]))

        for trip in report.get("roundTrips") or []:
            all_round_trips.append(_round_trip_row(trip, symbol=symbol, date=d))

        for ev in day_events:
            event_id += 1
            all_events.append(_event_row(ev, event_id=event_id, symbol=symbol))

        day_summaries.append(
            {
                "date": d,
                "trades": len(report.get("roundTrips") or []),
                "events": len(day_events),
                "pnl": report.get("pnl"),
                "phase": report.get("phase"),
                "referencePrice": report.get("referenceClose"),
                "result": report.get("result"),
                "candles": len(candles),
            }
        )

        daily_charts.append(
            {
                "date": d,
                "candles": candles,
                "trades": [_event_row(ev, event_id=i + 1, symbol=symbol) for i, ev in enumerate(day_events)],
                "roundTrips": [_round_trip_row(t, symbol=symbol, date=d) for t in report.get("roundTrips") or []],
                "levels": report.get("chartLevels") or [],
                "timeline": report.get("timeline") or [],
                "referenceClose": report.get("referenceClose"),
                "result": report.get("result"),
            }
        )

    summary = compute_backtest_statistics(
        daily_reports=daily_reports,
        all_round_trips=all_round_trips,
        skipped_days=len(skipped),
        total_calendar_days=len(dates),
    )

    last_report = daily_reports[-1] if daily_reports else {}
    levels = build_strategy_levels(cfg, {"referencePrice": last_report.get("referenceClose") or 0})
    ref_px = float(last_report.get("referenceClose") or 0)

    default_chart = daily_charts[-1] if daily_charts else {"candles": [], "trades": [], "levels": []}

    return {
        "ok": True,
        "message": f"Breakout backtest complete — {len(daily_reports)} trading day(s), {summary['totalTrades']} round-trip(s)",
        "instrument": symbol,
        "market": parsed["market"],
        "fromDate": from_date,
        "toDate": to_date,
        "daysRun": len(daily_reports),
        "skippedDays": len(skipped),
        "skippedDates": skipped,
        "summary": summary,
        "executionPolicy": EXECUTION_POLICY,
        "dailyReference": daily_reference,
        "dailyCharts": daily_charts,
        "strategyLevels": levels,
        "daySummaries": day_summaries,
        "trades": all_events,
        "roundTrips": all_round_trips,
        "candles": default_chart.get("candles") or [],
        "chartTrades": default_chart.get("trades") or [],
        "chartLevels": default_chart.get("levels") or [],
        "chartSubtitle": f"Ref {ref_px:.2f} · TP {parsed['take_profit']} · SL {parsed['stop_loss']}",
        "referencePrice": ref_px,
    }
