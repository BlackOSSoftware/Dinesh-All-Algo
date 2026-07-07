"""Strategy 3 SENSEX expiry-day ITM breakout backtest on StocksRin historical data."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.breakout_logic import (
    CandleBar,
    OptionSetup,
    build_trade_windows,
    evaluate_option_setup,
    find_bar_by_time,
    find_window_reference_bar,
    is_expiry_session_day,
    nearest_itm_ce_strike,
    nearest_itm_pe_strike,
    parse_config,
    parse_hhmm,
    reference_candle_end_hhmm,
    resample_bars,
    simulate_option_trade,
    validate_expiry_session_premium,
    bars_from_monitor_start,
)
from app.services.stocksrin_historical import (
    StocksRinFetchResult,
    fetch_index_candles,
    fetch_option_candles,
    get_auth_debug,
    stocksRin_configured,
)

LOG = logging.getLogger(__name__)

MAX_BACKTEST_DAYS = 90
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"

_EXECUTED = frozenset({
    "TARGET_HIT", "STOPLOSS_HIT", "MARKET_CLOSE", "MARKET_CLOSE_EXIT", "TP", "SL", "EOD", "CLOSED",
    "AMBIGUOUS",
})


def next_loss_recovery_multiplier(*, current_multiplier: int, pnl: float) -> int:
    """Double recovery size after a loss; reset after non-loss."""
    current = max(1, int(current_multiplier or 1))
    if pnl < 0:
        return current * 2
    return 1


def should_update_recovery_multiplier(status: str) -> bool:
    return status not in {"SKIPPED", "NO_TRADE", "PENDING_ENTRY", "DATA_ERROR"}


def _parse_date_range(from_date: str, to_date: str) -> list[str]:
    from datetime import datetime, timedelta

    start = datetime.strptime(from_date.strip()[:10], "%Y-%m-%d")
    end = datetime.strptime(to_date.strip()[:10], "%Y-%m-%d")
    if end < start:
        raise ValueError("to_date must be on or after from_date")
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _resolution(cfg: dict[str, Any]) -> int:
    return max(1, int(cfg.get("candleTimeframeMinutes") or cfg.get("windowGapMinutes") or 10))


def _window_session_end(last_window_hhmm: str) -> str:
    from app.services.breakout_logic import add_minutes_to_hhmm

    return add_minutes_to_hhmm(last_window_hhmm, 30)


def _bars(rows: list[dict[str, Any]], *, minutes: int | None = None) -> list[CandleBar]:
    raw = [
        CandleBar(
            time=str(r["time"]),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
        )
        for r in rows
    ]
    if minutes and minutes > 1:
        return resample_bars(raw, minutes, session_open_hhmm=MARKET_OPEN)
    return raw


def _chart_candles(rows: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    return [
        {
            "time": r["time"],
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r.get("volume", 0),
            "oi": r.get("oi", 0),
            "date": date,
        }
        for r in rows
    ]


def _fmt_clock(raw: str | None) -> str:
    if not raw:
        return ""
    t = str(raw).replace("T", " ")
    return t[11:16] if len(t) >= 16 else t[:5]


def _side_label(side: str) -> str:
    s = (side or "").upper()
    return "Call" if s == "CE" else "Put" if s == "PE" else side


def _contract_label(strike: float, side: str, expiry: str) -> str:
    return f"SENSEX {expiry[:10]} {int(strike) if strike == int(strike) else strike}{side}"


def _ohlc_dict(bar: CandleBar | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        "open": round(bar.open, 2),
        "high": round(bar.high, 2),
        "low": round(bar.low, 2),
        "close": round(bar.close, 2),
        "time": bar.time,
    }


def _is_closed(trade: dict[str, Any]) -> bool:
    return str(trade.get("status") or "") in _EXECUTED


def _clock_minutes(hhmm: str) -> int:
    hh, mm = parse_hhmm(hhmm[:5] if len(hhmm) >= 5 else hhmm)
    return hh * 60 + mm


def _trade_is_open_at(trade: dict[str, Any], at_hhmm: str) -> bool:
    """True if trade was entered and not yet exited at clock time (same day)."""
    if str(trade.get("status") or "") in ("NO_TRADE", "PENDING_ENTRY", "SKIPPED", "DATA_ERROR"):
        return False
    entry = (trade.get("entryTime") or _fmt_clock(str(trade.get("fillTime") or ""))).strip()
    if not entry or entry in ("N/A", "Not triggered", "Skipped"):
        return False
    exit_t = (trade.get("exitTimeFormatted") or _fmt_clock(str(trade.get("exitTime") or ""))).strip()
    at_m = _clock_minutes(at_hhmm)
    entry_m = _clock_minutes(entry)
    if entry_m > at_m:
        return False
    if not exit_t or str(trade.get("status") or "") == "PENDING_ENTRY":
        return True
    return entry_m <= at_m < _clock_minutes(exit_t)


def _any_trade_open_at(trades: list[dict[str, Any]], at_hhmm: str) -> bool:
    return any(_trade_is_open_at(t, at_hhmm) for t in trades)


def _skipped_leg_trade(
    *,
    trade_id: int,
    date: str,
    window: str,
    side: str,
    reason: str,
    lots: int,
) -> dict[str, Any]:
    return {
        "id": trade_id,
        "date": date,
        "window": window,
        "side": side,
        "sideLabel": _side_label(side),
        "status": "SKIPPED",
        "exitReason": "SKIPPED",
        "message": reason,
        "details": reason,
        "pnl": 0.0,
        "points": 0.0,
        "lots": lots,
        "sizeMultiplier": 1,
        "effectiveQuantity": lots,
        "dataSource": "StocksRin",
    }


def _data_error_trade(
    *,
    trade_id: int,
    date: str,
    window: str,
    side: str,
    strike: float,
    ref_bar: CandleBar | None,
    reason: str,
    fetch: StocksRinFetchResult | None,
    lots: int,
) -> dict[str, Any]:
    raw_snip = ""
    if fetch and fetch.raw is not None:
        raw_snip = json.dumps(fetch.raw, default=str)[:500]
    msg = reason if not raw_snip else f"{reason} | API: {raw_snip}"
    return {
        "id": trade_id,
        "date": date,
        "tradeDate": date,
        "expiry": date,
        "window": window,
        "side": side,
        "sideLabel": _side_label(side),
        "strike": strike,
        "referenceClose": ref_bar.close if ref_bar else None,
        "referenceTime": ref_bar.time if ref_bar else "",
        "status": "DATA_ERROR",
        "exitReason": "DATA_ERROR",
        "message": msg,
        "pnl": 0.0,
        "points": 0.0,
        "lots": lots,
        "sizeMultiplier": 1,
        "effectiveQuantity": lots,
        "dataSource": "StocksRin",
        "apiRequest": fetch.request if fetch else None,
    }


def _trade_record(
    *,
    trade_id: int,
    date: str,
    window: str,
    side: str,
    strike: float,
    ref_bar: CandleBar,
    setup: OptionSetup,
    sim: dict[str, Any] | None,
    lots: int,
    size_multiplier: int,
    chart_id: str,
    status: str,
    exit_reason: str,
    message: str = "",
    resolution: int = 10,
    total_session_candles: int | None = None,
    monitor_candles_after_ref: int | None = None,
) -> dict[str, Any]:
    pnl = float(sim.get("pnl") or 0) if sim else 0.0
    multiplier = max(1, int(size_multiplier or 1))
    effective_quantity = max(1, int(lots or 1)) * multiplier
    fill = sim.get("fill_time") if sim else None
    exit_t = sim.get("exit_time") if sim else None
    ref_end = reference_candle_end_hhmm(window, resolution)
    details: list[str] = []
    if message:
        details.append(message)
    elif exit_reason:
        details.append(exit_reason)
    if sim and sim.get("trigger_candle_high") is not None:
        details.append(f"Trigger H={sim['trigger_candle_high']} L={sim['trigger_candle_low']}")
    if status == "PENDING_ENTRY" and sim and sim.get("highest_during_monitoring") is not None:
        details.append(
            f"Highest during monitor={sim['highest_during_monitoring']} vs trigger={setup.entry_price}"
        )
    if exit_reason == "MARKET_CLOSE" and sim:
        lc = sim.get("last_candle_close") or sim.get("exit_price")
        details.append(f"Last candle close={lc}")
    if sim and sim.get("same_bar_tp_sl_conflict"):
        details.append(
            f"AMBIGUOUS same-bar TP+SL · best={sim.get('best_case_pnl')} worst={sim.get('worst_case_pnl')}"
            f" resolved={sim.get('resolved_as') or 'mark'}"
        )
    elif sim and sim.get("highest_after_entry") is not None:
        details.append(f"High after entry={sim['highest_after_entry']}")
    if sim and sim.get("lowest_after_entry") is not None:
        details.append(f"Low after entry={sim['lowest_after_entry']}")

    return {
        "id": trade_id,
        "date": date,
        "tradeDate": date,
        "expiry": date,
        "window": window,
        "side": side,
        "sideLabel": _side_label(side),
        "strike": strike,
        "referenceClose": ref_bar.close,
        "referenceTime": ref_bar.time,
        "referenceCandleStart": window,
        "referenceCandleEnd": ref_end,
        "referenceCloseTime": ref_end,
        "monitoringStartsAt": ref_end,
        "referencePrice": ref_bar.close,
        "optionSymbol": _contract_label(strike, side, date),
        "symbol": _contract_label(strike, side, date),
        "premiumClose": setup.premium_close,
        "entryPct": round((setup.entry_pct or 0) * 100, 2) if setup.entry_pct else None,
        "triggerPrice": setup.entry_price,
        "entryTriggerPrice": setup.entry_price,
        "entryPrice": sim.get("entry_price") if sim else setup.entry_price,
        "entryPremium": sim.get("entry_premium") if sim else setup.premium_close,
        "triggerCandleHigh": sim.get("trigger_candle_high") if sim else None,
        "triggerCandleLow": sim.get("trigger_candle_low") if sim else None,
        "targetPrice": setup.target_price,
        "target": setup.target_price,
        "stopPrice": setup.stop_price,
        "stopLoss": setup.stop_price,
        "entryTime": _fmt_clock(str(fill or "")),
        "fillTime": fill,
        "exitTime": exit_t,
        "exitTimeFormatted": _fmt_clock(str(exit_t or "")),
        "exitPrice": sim.get("exit_price") if sim else None,
        "lastCandleClose": sim.get("last_candle_close") if sim else None,
        "exitReason": exit_reason,
        "tradeDuration": sim.get("trade_duration_minutes") if sim else None,
        "tradeDurationMinutes": sim.get("trade_duration_minutes") if sim else None,
        "status": status,
        "message": message or exit_reason,
        "details": " · ".join(details),
        "pnl": round(pnl * effective_quantity, 2),
        "points": round(float(sim.get("points") or pnl), 2) if sim else 0.0,
        "lots": lots,
        "sizeMultiplier": multiplier,
        "effectiveQuantity": effective_quantity,
        "chartId": chart_id,
        "dataSource": "StocksRin",
        "highestAfterEntry": sim.get("highest_after_entry") if sim else None,
        "highestPremiumAfterEntry": sim.get("highest_after_entry") if sim else None,
        "lowestAfterEntry": sim.get("lowest_after_entry") if sim else None,
        "lowestPremiumAfterEntry": sim.get("lowest_after_entry") if sim else None,
        "highestPremiumDuringMonitoring": sim.get("highest_during_monitoring") if sim else None,
        "totalSessionCandles": total_session_candles,
        "monitorCandlesAfterRef": monitor_candles_after_ref or (sim.get("monitor_candle_count") if sim else None),
        "monitorResolutionMinutes": sim.get("monitor_resolution_minutes") if sim else None,
        "sameBarTpSlConflict": sim.get("same_bar_tp_sl_conflict") if sim else None,
        "bestCasePnl": sim.get("best_case_pnl") if sim else None,
        "worstCasePnl": sim.get("worst_case_pnl") if sim else None,
        "noLookAhead": True,
    }


def _debug_row(
    *,
    date: str,
    window: str,
    side: str,
    ref_bar: CandleBar | None,
    ref_option_bar: CandleBar | None,
    strike: float,
    premium: float | None,
    setup: OptionSetup | None,
    sim: dict[str, Any] | None,
    target_price: float | None,
    stop_price: float | None,
    exit_reason: str | None,
    status: str,
    reason: str,
    resolution: int,
    total_session_candles: int,
    monitor_candles_after_ref: int,
) -> dict[str, Any]:
    label = _contract_label(strike, side, date)
    fill_bar = sim.get("fill_bar") if sim else None
    exit_bar = sim.get("exit_bar") if sim else None
    fill_time = sim.get("fill_time") if sim else None
    exit_time = sim.get("exit_time") if sim else None
    ref_end = reference_candle_end_hhmm(window, resolution) if window else ""
    return {
        "date": date,
        "window": window,
        "side": side,
        "referenceTime": ref_end,
        "referenceCandleStart": window,
        "referenceCandleEnd": ref_end,
        "monitoringStartsAt": ref_end,
        "referencePrice": round(ref_bar.close, 2) if ref_bar else None,
        "referenceClose": round(ref_bar.close, 2) if ref_bar else None,
        "referenceOhlc": _ohlc_dict(ref_bar),
        "referenceOptionOhlc": _ohlc_dict(ref_option_bar),
        "strike": strike,
        "expectedSymbol": label,
        "resolvedSymbol": label,
        "actualSymbol": label,
        "premiumClose": round(premium, 2) if premium is not None else None,
        "totalSessionCandles": total_session_candles,
        "monitorCandlesAfterRef": monitor_candles_after_ref,
        "historicalCandleCount": monitor_candles_after_ref,
        "entryPct": round((setup.entry_pct or 0) * 100, 2) if setup and setup.entry_pct else None,
        "triggerPrice": setup.entry_price if setup else None,
        "entryPrice": setup.entry_price if setup else None,
        "entryTriggerPrice": setup.entry_price if setup else None,
        "targetPrice": target_price,
        "stopPrice": stop_price,
        "triggerFound": fill_time is not None,
        "triggerCandleTime": fill_time,
        "triggerCandleHigh": sim.get("trigger_candle_high") if sim else None,
        "triggerCandleLow": sim.get("trigger_candle_low") if sim else None,
        "triggerCandleOhlc": _ohlc_dict(fill_bar if isinstance(fill_bar, CandleBar) else None),
        "exitCandleTime": exit_time,
        "exitCandleOhlc": _ohlc_dict(exit_bar if isinstance(exit_bar, CandleBar) else None),
        "highestAfterEntry": sim.get("highest_after_entry") if sim else None,
        "highestPremiumAfterEntry": sim.get("highest_after_entry") if sim else None,
        "lowestAfterEntry": sim.get("lowest_after_entry") if sim else None,
        "lowestPremiumAfterEntry": sim.get("lowest_after_entry") if sim else None,
        "highestPremiumDuringMonitoring": sim.get("highest_during_monitoring") if sim else None,
        "lastCandleClose": sim.get("last_candle_close") if sim else None,
        "sameBarTpSlConflict": sim.get("same_bar_tp_sl_conflict") if sim else None,
        "bestCasePnl": sim.get("best_case_pnl") if sim else None,
        "worstCasePnl": sim.get("worst_case_pnl") if sim else None,
        "monitorResolutionMinutes": sim.get("monitor_resolution_minutes") if sim else None,
        "noLookAhead": True,
        "exitReason": exit_reason,
        "status": status,
        "reason": reason,
        "dataSource": "StocksRin",
    }


def _leg_dict(setup: OptionSetup, strike: float, side: str, expiry: str) -> dict[str, Any]:
    return {
        "strike": setup.strike or strike,
        "premiumClose": round(setup.premium_close, 2),
        "entryPct": round((setup.entry_pct or 0) * 100, 2) if setup.entry_pct else None,
        "triggerPrice": setup.entry_price,
        "targetPrice": setup.target_price,
        "stopPrice": setup.stop_price,
        "tradable": setup.tradable,
        "skipReason": setup.skip_reason,
        "symbol": _contract_label(strike, side, expiry),
        "expiry": expiry,
        "token": None,
    }


def _build_analysis(trades: list[dict[str, Any]], expiry_days: int) -> dict[str, Any]:
    closed = [t for t in trades if _is_closed(t)]
    points = [float(t.get("points") or 0) for t in closed]
    return {
        "tpHits": sum(1 for t in closed if t.get("exitReason") in ("TP", "TARGET_HIT")),
        "slHits": sum(1 for t in closed if t.get("exitReason") in ("SL", "STOPLOSS_HIT")),
        "eodExits": sum(1 for t in closed if t.get("exitReason") in ("EOD", "MARKET_CLOSE", "MARKET_CLOSE_EXIT")),
        "pending": sum(1 for t in trades if t.get("status") == "PENDING_ENTRY"),
        "noTrade": sum(1 for t in trades if t.get("status") == "NO_TRADE"),
        "dataErrors": sum(1 for t in trades if t.get("status") == "DATA_ERROR"),
        "skipped": sum(1 for t in trades if t.get("status") == "SKIPPED"),
        "ambiguous": sum(1 for t in trades if t.get("status") == "AMBIGUOUS"),
        "totalPoints": round(sum(points), 2),
        "totalPnl": round(sum(float(t.get("pnl") or 0) for t in closed), 2),
        "winTrades": sum(1 for p in points if p > 0),
        "lossTrades": sum(1 for p in points if p < 0),
        "breakevenTrades": sum(1 for p in points if p == 0),
        "grossProfit": round(sum(p for p in points if p > 0), 2),
        "grossLoss": round(sum(p for p in points if p < 0), 2),
        "closedTrades": len(closed),
        "expiryDays": expiry_days,
    }


def _simulate_leg(
    *,
    date: str,
    window: str,
    side: str,
    strike: float,
    ref_bar: CandleBar,
    cfg: dict[str, Any],
    resolution: int,
    session_end: str,
    lots: int,
    size_multiplier: int,
    trade_id: int,
) -> tuple[dict[str, Any], OptionSetup, list[dict[str, Any]] | None, dict[str, Any]]:
    """Returns (trade, setup, chart_series_entry|None, debug_row)."""
    chart_id = f"{date}|{window}|{side}"
    opt_fetch = fetch_option_candles(
        date=date,
        expiry=date,
        strike=strike,
        option_type=side,
        resolution=resolution,
        start_hhmm=MARKET_OPEN,
        end_hhmm=session_end,
    )
    if not opt_fetch.ok:
        setup = OptionSetup(
            side=side, strike=strike, premium_close=0.0,
            entry_pct=None, entry_price=None, target_price=None, stop_price=None,
            tradable=False, skip_reason=opt_fetch.error or "Option fetch failed",
        )
        if opt_fetch.auth_error:
            trade = _data_error_trade(
                trade_id=trade_id, date=date, window=window, side=side, strike=strike,
                ref_bar=ref_bar, reason=opt_fetch.error or "StocksRin authentication failed", fetch=opt_fetch, lots=lots,
            )
            trade["authError"] = True
            dbg = _debug_row(
                date=date, window=window, side=side, ref_bar=ref_bar, ref_option_bar=None,
                strike=strike, premium=None, setup=setup, sim=None,
                target_price=None, stop_price=None, exit_reason="DATA_ERROR",
                status="DATA_ERROR", reason=trade["message"], resolution=resolution,
                total_session_candles=0, monitor_candles_after_ref=0,
            )
            return trade, setup, None, dbg
        trade = _data_error_trade(
            trade_id=trade_id, date=date, window=window, side=side, strike=strike,
            ref_bar=ref_bar, reason=opt_fetch.error or "Option fetch failed", fetch=opt_fetch, lots=lots,
        )
        dbg = _debug_row(
            date=date, window=window, side=side, ref_bar=ref_bar, ref_option_bar=None,
            strike=strike, premium=None, setup=setup, sim=None,
            target_price=None, stop_price=None, exit_reason="DATA_ERROR",
            status="DATA_ERROR", reason=trade["message"], resolution=resolution,
            total_session_candles=0, monitor_candles_after_ref=0,
        )
        return trade, setup, None, dbg

    opt_bars = _bars(opt_fetch.candles, minutes=resolution)
    raw_1m = _bars(opt_fetch.candles, minutes=1)
    ref_idx = find_bar_by_time(opt_bars, ref_bar.time)
    if ref_idx is None:
        for i, bar in enumerate(opt_bars):
            if _fmt_clock(bar.time) == _fmt_clock(ref_bar.time):
                ref_idx = i
                break
    ref_option_bar = opt_bars[ref_idx] if ref_idx is not None else None
    premium = ref_option_bar.close if ref_option_bar is not None else None
    monitor_start = reference_candle_end_hhmm(window, resolution)
    monitor_1m = bars_from_monitor_start(raw_1m, monitor_start)
    total_session = len(raw_1m)
    monitor_count = len(monitor_1m)

    if premium is None:
        reason = f"No option candle at reference {_fmt_clock(ref_bar.time)} for {_contract_label(strike, side, date)}"
        setup = OptionSetup(
            side=side, strike=strike, premium_close=0.0,
            entry_pct=None, entry_price=None, target_price=None, stop_price=None,
            tradable=False, skip_reason=reason,
        )
        trade = _data_error_trade(
            trade_id=trade_id, date=date, window=window, side=side, strike=strike,
            ref_bar=ref_bar, reason=reason, fetch=opt_fetch, lots=lots,
        )
        dbg = _debug_row(
            date=date, window=window, side=side, ref_bar=ref_bar, ref_option_bar=None,
            strike=strike, premium=None, setup=setup, sim=None,
            target_price=None, stop_price=None, exit_reason="DATA_ERROR",
            status="DATA_ERROR", reason=reason, resolution=resolution,
            total_session_candles=total_session, monitor_candles_after_ref=0,
        )
        return trade, setup, None, dbg

    data_err = validate_expiry_session_premium(side, strike, ref_bar.close, premium, cfg=cfg)
    if data_err:
        setup = OptionSetup(
            side=side, strike=strike, premium_close=premium,
            entry_pct=None, entry_price=None, target_price=None, stop_price=None,
            tradable=False, skip_reason=data_err,
        )
        trade = _data_error_trade(
            trade_id=trade_id, date=date, window=window, side=side, strike=strike,
            ref_bar=ref_bar, reason=data_err, fetch=opt_fetch, lots=lots,
        )
        dbg = _debug_row(
            date=date, window=window, side=side, ref_bar=ref_bar, ref_option_bar=ref_option_bar,
            strike=strike, premium=premium, setup=setup, sim=None,
            target_price=None, stop_price=None, exit_reason="DATA_ERROR",
            status="DATA_ERROR", reason=data_err, resolution=resolution,
            total_session_candles=total_session, monitor_candles_after_ref=monitor_count,
        )
        return trade, setup, None, dbg

    setup = evaluate_option_setup(
        side=side,
        strike=strike,
        premium_close=premium,
        target_pct=float(cfg.get("targetPercent") or 25),
        stop_pct=float(cfg.get("stopLossPercent") or 30),
        cfg=cfg,
    )

    chart = {
        "id": chart_id,
        "date": date,
        "window": window,
        "side": side,
        "sideLabel": _side_label(side),
        "strike": setup.strike,
        "symbol": _contract_label(strike, side, date),
        "referenceClose": round(ref_bar.close, 2),
        "referenceTime": ref_bar.time,
        "candles": [
            {
                "time": b.time,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": 0,
                "oi": 0,
                "date": date,
            }
            for b in opt_bars
        ],
        "levels": {
            "premiumClose": setup.premium_close,
            "trigger": setup.entry_price,
            "target": setup.target_price,
            "stop": setup.stop_price,
        },
    }

    if not setup.tradable:
        trade = _trade_record(
            trade_id=trade_id, date=date, window=window, side=side, strike=strike,
            ref_bar=ref_bar, setup=setup, sim=None, lots=lots, size_multiplier=size_multiplier, chart_id=chart_id,
            status="NO_TRADE", exit_reason="NO_TRADE", message=setup.skip_reason or "Not eligible",
            resolution=resolution, total_session_candles=total_session, monitor_candles_after_ref=monitor_count,
        )
        dbg = _debug_row(
            date=date, window=window, side=side, ref_bar=ref_bar, ref_option_bar=ref_option_bar,
            strike=strike, premium=premium, setup=setup, sim=None,
            target_price=setup.target_price, stop_price=setup.stop_price,
            exit_reason="NO_TRADE", status="NO_TRADE",
            reason=setup.skip_reason or "Not eligible", resolution=resolution,
            total_session_candles=total_session, monitor_candles_after_ref=monitor_count,
        )
        return trade, setup, chart, dbg

    sim = simulate_option_trade(
        monitor_1m,
        setup,
        start_idx=0,
        ambiguous_policy=str(cfg.get("ambiguousExitPolicy") or "conservative"),
        monitor_resolution_minutes=1,
    )
    exit_reason = str(sim.get("exit_reason") or "PENDING_ENTRY")
    status = str(sim.get("status") or exit_reason)

    trade = _trade_record(
        trade_id=trade_id, date=date, window=window, side=side, strike=setup.strike,
        ref_bar=ref_bar, setup=setup, sim=sim, lots=lots, size_multiplier=size_multiplier, chart_id=chart_id,
        status=status, exit_reason=exit_reason,
        resolution=resolution, total_session_candles=total_session, monitor_candles_after_ref=monitor_count,
    )
    dbg = _debug_row(
        date=date, window=window, side=side, ref_bar=ref_bar, ref_option_bar=ref_option_bar,
        strike=strike, premium=premium, setup=setup, sim=sim,
        target_price=setup.target_price, stop_price=setup.stop_price,
        exit_reason=exit_reason, status=status,
        reason=exit_reason if sim.get("fill_time") else (setup.skip_reason or exit_reason),
        resolution=resolution,
        total_session_candles=total_session, monitor_candles_after_ref=monitor_count,
    )
    return trade, setup, chart, dbg


def _simulate_day(date: str, cfg: dict[str, Any]) -> dict[str, Any]:
    base_lots = max(1, int(cfg.get("quantity") or 1))
    current_multiplier = 1
    resolution = _resolution(cfg)
    windows = build_trade_windows(
        str(cfg.get("startTime") or "14:35"),
        count=int(cfg.get("windowCount") or 3),
        gap_minutes=int(cfg.get("windowGapMinutes") or 10),
    )
    session_end = MARKET_CLOSE

    idx_fetch = fetch_index_candles(
        date,
        resolution=resolution,
        start_hhmm=MARKET_OPEN,
        end_hhmm=MARKET_CLOSE,
    )
    if not idx_fetch.ok or not idx_fetch.candles:
        if idx_fetch.auth_error:
            reason = idx_fetch.error or "StocksRin session expired. Historical data could not be loaded. Please login again."
            return {
                "date": date,
                "skipped": True,
                "failed": True,
                "authError": True,
                "dataError": True,
                "reason": reason,
                "candleDebug": idx_fetch.request,
                "trades": [],
                "pnl": 0.0,
                "setups": [],
                "chartSeries": [],
                "debugRows": [],
            }
        reason = idx_fetch.error or "No SENSEX index candles from StocksRin"
        LOG.error("SENSEX index load failed %s: %s", date, reason)
        return {
            "date": date,
            "skipped": True,
            "failed": True,
            "dataError": True,
            "reason": reason,
            "candleDebug": idx_fetch.request,
            "apiResponse": idx_fetch.raw,
            "trades": [],
            "pnl": 0.0,
            "setups": [],
            "chartSeries": [],
            "debugRows": [],
        }

    index_bars = _bars(idx_fetch.candles, minutes=resolution)
    trades: list[dict[str, Any]] = []
    setups: list[dict[str, Any]] = []
    chart_series: list[dict[str, Any]] = []
    debug_rows: list[dict[str, Any]] = []
    day_pnl = 0.0
    trade_id = 0
    exec_mode = str(cfg.get("windowExecutionMode") or "independent").lower()
    one_at_a_time = bool(cfg.get("oneTradeAtATime"))

    for win in windows:
        ref_end = reference_candle_end_hhmm(win.start_hhmm, resolution)

        if exec_mode == "sequential" and win.index > 0 and _any_trade_open_at(trades, ref_end):
            trades.append({
                "id": trade_id, "date": date, "window": win.start_hhmm, "side": "-",
                "status": "SKIPPED", "exitReason": "SKIPPED",
                "message": f"Prior trade still open at {ref_end} (sequential mode)",
                "details": f"Prior trade still open at {ref_end} (sequential mode)",
                "pnl": 0.0, "points": 0.0,
            })
            trade_id += 1
            continue

        ref_bar = find_window_reference_bar(index_bars, win.start_hhmm, window_minutes=resolution)
        if ref_bar is None:
            trades.append({
                "id": trade_id, "date": date, "window": win.start_hhmm, "side": "-",
                "status": "SKIPPED", "message": "Reference candle not found", "pnl": 0.0, "points": 0.0,
            })
            trade_id += 1
            continue

        ce_strike = nearest_itm_ce_strike(ref_bar.close)
        pe_strike = nearest_itm_pe_strike(ref_bar.close)
        window_setups: dict[str, OptionSetup] = {}

        for side, strike in [("CE", ce_strike), ("PE", pe_strike)]:
            if one_at_a_time and _any_trade_open_at(trades, ref_end):
                skip = _skipped_leg_trade(
                    trade_id=trade_id, date=date, window=win.start_hhmm, side=side,
                    reason=f"One trade at a time — prior leg still open at {ref_end}",
                    lots=base_lots,
                )
                trades.append(skip)
                trade_id += 1
                continue

            trade, setup, chart, dbg = _simulate_leg(
                date=date, window=win.start_hhmm, side=side, strike=strike,
                ref_bar=ref_bar, cfg=cfg, resolution=resolution,
                session_end=session_end, lots=base_lots, size_multiplier=current_multiplier, trade_id=trade_id,
            )
            window_setups[side] = setup
            trades.append(trade)
            debug_rows.append(dbg)
            if chart:
                chart_series.append(chart)
            trade_id += 1
            if trade.get("authError"):
                return {
                    "date": date,
                    "skipped": True,
                    "failed": True,
                    "authError": True,
                    "dataError": True,
                    "reason": trade.get("message") or "StocksRin session expired. Please login again.",
                    "trades": trades,
                    "pnl": round(day_pnl, 2),
                    "setups": setups,
                    "chartSeries": chart_series,
                    "debugRows": debug_rows,
                }
            day_pnl += float(trade.get("pnl") or 0)
            if should_update_recovery_multiplier(str(trade.get("status") or "")):
                pnl = float(trade.get("pnl") or 0)
                current_multiplier = next_loss_recovery_multiplier(
                    current_multiplier=current_multiplier,
                    pnl=pnl,
                )

        ce = window_setups.get("CE") or evaluate_option_setup(
            side="CE", strike=ce_strike, premium_close=0.0,
            target_pct=float(cfg.get("targetPercent") or 25),
            stop_pct=float(cfg.get("stopLossPercent") or 30), cfg=cfg,
        )
        pe = window_setups.get("PE") or evaluate_option_setup(
            side="PE", strike=pe_strike, premium_close=0.0,
            target_pct=float(cfg.get("targetPercent") or 25),
            stop_pct=float(cfg.get("stopLossPercent") or 30), cfg=cfg,
        )
        setups.append({
            "window": win.start_hhmm,
            "referenceClose": round(ref_bar.close, 2),
            "referenceTime": ref_bar.time,
            "referenceCandleEnd": ref_end,
            "ce": _leg_dict(ce, ce_strike, "CE", date),
            "pe": _leg_dict(pe, pe_strike, "PE", date),
        })

    return {
        "date": date,
        "skipped": False,
        "candles": _chart_candles(idx_fetch.candles, date),
        "trades": trades,
        "pnl": round(day_pnl, 2),
        "windows": len(windows),
        "setups": setups,
        "chartSeries": chart_series,
        "debugRows": debug_rows,
    }


def _auth_failure_result(
    from_date: str,
    to_date: str,
    cfg: dict[str, Any],
    message: str,
    day_summaries: list[dict[str, Any]],
    day_details: list[dict[str, Any]],
    skipped_dates: list[str],
    failed_days: int,
    all_trades: list[dict[str, Any]],
    debug_rows_all: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "fromDate": from_date,
        "toDate": to_date,
        "daysRun": 0,
        "failedDays": failed_days,
        "skippedDays": len(skipped_dates),
        "skippedDates": skipped_dates,
        "sessionError": message,
        "stocksRinAuth": get_auth_debug(),
        "dataSource": "StocksRin",
        "summary": {"totalTrades": 0, "totalPnl": 0.0, "winDays": 0, "lossDays": 0, "netDays": len(day_summaries)},
        "analysis": _build_analysis(all_trades, len(day_summaries)),
        "daySummaries": day_summaries,
        "dayDetails": day_details,
        "trades": all_trades,
        "tradeRecords": all_trades,
        "candles": [],
        "chartSeries": [],
        "debugRows": debug_rows_all,
        "chartTrades": [],
        "config": cfg,
        "windows": [
            {"index": w.index, "start_hhmm": w.start_hhmm}
            for w in build_trade_windows(
                str(cfg.get("startTime") or "14:35"),
                count=int(cfg.get("windowCount") or 3),
                gap_minutes=int(cfg.get("windowGapMinutes") or 10),
            )
        ],
    }


def run_breakout_backtest(params: dict[str, Any]) -> dict[str, Any]:
    cfg = parse_config(params.get("config") or params)
    from_date = str(params.get("fromDate") or params.get("from_date") or "")
    to_date = str(params.get("toDate") or params.get("to_date") or "")
    if not from_date or not to_date:
        raise ValueError("fromDate and toDate are required")

    dates = _parse_date_range(from_date, to_date)
    if len(dates) > MAX_BACKTEST_DAYS:
        raise ValueError(f"Maximum {MAX_BACKTEST_DAYS} days per backtest")

    config_err: str | None = None
    if not stocksRin_configured():
        config_err = (
            "StocksRin not configured. Set STOCKSRIN_APP_AUTHORIZATION, STOCKSRIN_EMAIL, "
            "STOCKSRIN_PASSWORD_B64 in .env then run: python scripts/import_stocksrin_session.py --login"
        )

    all_trades: list[dict[str, Any]] = []
    all_candles: list[dict[str, Any]] = []
    day_summaries: list[dict[str, Any]] = []
    day_details: list[dict[str, Any]] = []
    chart_series_all: list[dict[str, Any]] = []
    debug_rows_all: list[dict[str, Any]] = []
    skipped_dates: list[str] = []
    total_pnl = 0.0
    win_days = loss_days = failed_days = 0
    serial = 1

    if config_err:
        return {
            "ok": False,
            "message": config_err,
            "fromDate": from_date,
            "toDate": to_date,
            "daysRun": 0,
            "failedDays": 0,
            "skippedDays": 0,
            "skippedDates": [],
            "sessionError": config_err,
            "stocksRinAuth": get_auth_debug(),
            "dataSource": "StocksRin",
            "summary": {"totalTrades": 0, "totalPnl": 0.0, "winDays": 0, "lossDays": 0, "netDays": 0},
            "analysis": _build_analysis([], 0),
            "daySummaries": [],
            "dayDetails": [],
            "trades": [],
            "tradeRecords": [],
            "candles": [],
            "chartSeries": [],
            "debugRows": [],
            "chartTrades": [],
            "config": cfg,
            "windows": [
                {"index": w.index, "start_hhmm": w.start_hhmm}
                for w in build_trade_windows(
                    str(cfg.get("startTime") or "14:35"),
                    count=int(cfg.get("windowCount") or 3),
                    gap_minutes=int(cfg.get("windowGapMinutes") or 10),
                )
            ],
        }

    for date in dates:
        if not is_expiry_session_day(date, cfg):
            skipped_dates.append(date)
            continue
        try:
            day = _simulate_day(date, cfg)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Backtest day %s failed: %s", date, exc)
            failed_days += 1
            day_summaries.append({"date": date, "trades": 0, "pnl": 0.0, "error": str(exc), "failed": True})
            day_details.append({"date": date, "pnl": 0.0, "setups": [], "chartSeries": [], "error": str(exc)})
            continue

        if day.get("skipped"):
            skipped_dates.append(date)
            if day.get("dataError") or day.get("authError"):
                failed_days += 1
            if day.get("authError"):
                auth_msg = day.get("reason") or "StocksRin session expired. Historical data could not be loaded. Please login again."
                return _auth_failure_result(
                    from_date, to_date, cfg, auth_msg, day_summaries, day_details,
                    skipped_dates, failed_days, all_trades, debug_rows_all,
                )
            day_summaries.append({
                "date": date, "trades": 0, "pnl": 0.0,
                "error": day.get("reason") or "Skipped", "failed": True,
                "candleDebug": day.get("candleDebug"),
            })
            day_details.append({
                "date": date, "pnl": 0.0, "setups": [], "chartSeries": [],
                "error": day.get("reason"), "candleDebug": day.get("candleDebug"),
            })
            continue

        for t in day.get("trades") or []:
            t["serialNo"] = serial
            t["id"] = serial
            serial += 1
            all_trades.append(t)

        all_candles.extend(day.get("candles") or [])
        chart_series_all.extend(day.get("chartSeries") or [])
        debug_rows_all.extend(day.get("debugRows") or [])
        pnl = float(day.get("pnl") or 0)
        total_pnl += pnl
        if pnl > 0:
            win_days += 1
        elif pnl < 0:
            loss_days += 1

        closed_n = len([t for t in day.get("trades") or [] if _is_closed(t)])
        day_summaries.append({"date": date, "trades": closed_n, "pnl": pnl, "candles": len(day.get("candles") or [])})
        day_details.append({
            "date": date, "pnl": pnl,
            "setups": day.get("setups") or [],
            "chartSeries": day.get("chartSeries") or [],
        })

    closed = [t for t in all_trades if _is_closed(t)]
    analysis = _build_analysis(all_trades, len(day_summaries))
    ok_days = len([d for d in day_summaries if not d.get("failed")])

    return {
        "ok": True,
        "message": f"StocksRin backtest — {ok_days} expiry day(s), {len(closed)} closed trades"
        + (f", {failed_days} failed" if failed_days else "")
        + (f", {analysis.get('dataErrors', 0)} data errors" if analysis.get("dataErrors") else ""),
        "fromDate": from_date,
        "toDate": to_date,
        "daysRun": ok_days,
        "failedDays": failed_days,
        "skippedDays": len(skipped_dates),
        "skippedDates": skipped_dates,
        "dataSource": "StocksRin",
        "summary": {
            "totalTrades": len(closed),
            "totalPnl": round(total_pnl, 2),
            "winDays": win_days,
            "lossDays": loss_days,
            "netDays": len(day_summaries),
        },
        "analysis": analysis,
        "daySummaries": day_summaries,
        "dayDetails": day_details,
        "trades": all_trades,
        "tradeRecords": all_trades,
        "candles": all_candles,
        "chartSeries": chart_series_all,
        "debugRows": debug_rows_all,
        "sessionError": None,
        "stocksRinAuth": get_auth_debug(),
        "chartTrades": closed,
        "config": cfg,
        "windows": [
            {"index": w.index, "start_hhmm": w.start_hhmm}
            for w in build_trade_windows(
                str(cfg.get("startTime") or "14:35"),
                count=int(cfg.get("windowCount") or 3),
                gap_minutes=int(cfg.get("windowGapMinutes") or 10),
            )
        ],
    }
