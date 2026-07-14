"""
Angel One live market quote â€” proxied through backend so keys stay server-side.

Browser calls GET /angel/live-quote with **Indian Algo** JWT only.
Angel `jwt_token` + `api_key` come from `backend/.env` (see `.env.example`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.deps import get_current_user
from app.models import User
from app.services.angel_candles import post_get_candle_data
from app.services.angel_quote import post_market_quote, _truthy_status
from app.services.sensex_quote import fetch_sensex_live_quote

LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/angel", tags=["angel"])

_CACHE: dict[str, Any] = {"t": 0.0, "payload": None}
_CACHE_TTL_SEC = 1.0  # Keep live price responsive while still coalescing duplicate dashboard polls.

_START_BAR_CACHE: dict[str, Any] = {"t": 0.0, "key": "", "payload": None}
_START_BAR_CACHE_TTL_SEC = 180.0  # Start-bar for "today" changes rarely; eases candle API pressure.
_LAST_SESSION_LOOKBACK_DAYS = 10

_HIST_DAY_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_HIST_DAY_CACHE_TTL_SEC = 600.0  # 10 min per date â€” speeds repeat backtests
_HIST_DAY_CACHE_MAX = 1200

_INTERVAL_MAP = {
    "1": "ONE_MINUTE",
    "3": "THREE_MINUTE",
    "5": "FIVE_MINUTE",
    "10": "TEN_MINUTE",
    "15": "FIFTEEN_MINUTE",
    "30": "THIRTY_MINUTE",
    "60": "ONE_HOUR",
    "ONE_MINUTE": "ONE_MINUTE",
    "THREE_MINUTE": "THREE_MINUTE",
    "FIVE_MINUTE": "FIVE_MINUTE",
    "TEN_MINUTE": "TEN_MINUTE",
    "FIFTEEN_MINUTE": "FIFTEEN_MINUTE",
    "THIRTY_MINUTE": "THIRTY_MINUTE",
    "ONE_HOUR": "ONE_HOUR",
}


def clear_angel_caches() -> None:
    """Clear live-quote and start-bar caches (e.g. after JWT refresh)."""
    global _CACHE, _START_BAR_CACHE
    _CACHE = {"t": 0.0, "payload": None}
    _START_BAR_CACHE = {"t": 0.0, "key": "", "payload": None}
    try:
        from app.services.market_ltp import clear_market_ltp_cache

        clear_market_ltp_cache()
    except Exception:  # noqa: BLE001
        pass


def _asia_kolkata_tz():
    """IST for session dates. Windows needs `tzdata` package; else UTC+05:30 fallback."""
    try:
        return ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=5, minutes=30))


def _parse_candle_row(row: Any) -> tuple[str | None, float | None, float | None, float | None, float | None]:
    """Angel returns each candle as [datetime, open, high, low, close, volume] or similar."""
    if isinstance(row, (list, tuple)) and len(row) >= 5:
        dt = str(row[0]) if row[0] is not None else None
        try:
            o = float(row[1])
            h = float(row[2])
            l = float(row[3])
            c = float(row[4])
            return dt, o, h, l, c
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
                    continue
            return None

        o = _f("open", "Open")
        h = _f("high", "High")
        l_ = _f("low", "Low")
        c = _f("close", "Close", "ltp", "Ltp")
        return dt, o, h, l_, c
    return None, None, None, None, None


def _parse_exchange_tokens(raw: str) -> dict[str, list[str]]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=503,
            detail=f"ANGEL_EXCHANGE_TOKENS must be valid JSON: {e}",
        ) from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="ANGEL_EXCHANGE_TOKENS must be a JSON object")
    out: dict[str, list[str]] = {}
    for ex, tokens in data.items():
        if not isinstance(ex, str):
            continue
        if isinstance(tokens, list):
            out[ex.upper()] = [str(t).strip() for t in tokens if str(t).strip()]
        elif isinstance(tokens, str):
            out[ex.upper()] = [tokens.strip()] if tokens.strip() else []
    return out


@router.get("/live-quote")
def angel_live_quote(_user: User = Depends(get_current_user)):
    """
    Cached live quote (LTP/OHLC/FULL per `ANGEL_QUOTE_MODE`).
    Response includes normalized `fetched` / `unfetched` when Angel returns them.
    """
    from app.services.angel_jwt_refresh import reload_angel_tokens_from_env

    reload_angel_tokens_from_env()

    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(
            status_code=503,
            detail="Angel One not configured: set ANGEL_API_KEY and ANGEL_JWT_TOKEN in backend/.env",
        )

    exchange_tokens = _parse_exchange_tokens(settings.angel_exchange_tokens)
    if not exchange_tokens:
        raise HTTPException(
            status_code=503,
            detail='Set ANGEL_EXCHANGE_TOKENS JSON, e.g. {"BSE":["99919000"]} for SENSEX or {"NSE":["3045"]} for SBIN',
        )

    mode = (settings.angel_quote_mode or "LTP").strip().upper()
    if mode not in ("LTP", "OHLC", "FULL"):
        mode = "LTP"

    now = time.monotonic()
    if _CACHE["payload"] is not None and now - float(_CACHE["t"]) < _CACHE_TTL_SEC:
        return _CACHE["payload"]

    try:
        out = fetch_sensex_live_quote(exchange_tokens=exchange_tokens, mode=mode)
        if settings.angel_debug:
            out["raw"] = None
    except Exception as e:  # noqa: BLE001
        LOG.exception("Angel quote unexpected error")
        raise HTTPException(status_code=502, detail=str(e)) from e

    _CACHE["t"] = now
    _CACHE["payload"] = out
    return out


def _parse_start_hhmm(start: str) -> tuple[int, int]:
    s = (start or "").strip()
    # HTML time can be "09:15" or "09:15:00"
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", s)
    if not m:
        raise HTTPException(status_code=422, detail="Query `start` must be HH:MM (e.g. 09:15)")
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise HTTPException(status_code=422, detail="Invalid time in `start`")
    return hh, mm


def _parse_yyyy_mm_dd(value: str, name: str = "date") -> tuple[int, int, int]:
    s = (value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if not m:
        raise HTTPException(status_code=422, detail=f"Query `{name}` must be YYYY-MM-DD")
    yy, mo, dd = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    try:
        datetime(yy, mo, dd)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid `{name}`") from e
    return yy, mo, dd


def _primary_exchange_token() -> tuple[str, str]:
    exchange_tokens = _parse_exchange_tokens(settings.angel_exchange_tokens)
    if not exchange_tokens:
        raise HTTPException(
            status_code=503,
            detail='Set ANGEL_EXCHANGE_TOKENS JSON, e.g. {"BSE":["99919000"]} for SENSEX',
        )
    exchange = next(iter(exchange_tokens.keys()))
    tokens = exchange_tokens[exchange]
    if not tokens:
        raise HTTPException(status_code=503, detail="ANGEL_EXCHANGE_TOKENS has empty token list")
    return exchange, tokens[0]


def _iter_dates(from_date: str, to_date: str) -> list[str]:
    yy0, mo0, dd0 = _parse_yyyy_mm_dd(from_date, "from_date")
    yy1, mo1, dd1 = _parse_yyyy_mm_dd(to_date, "to_date")
    start = datetime(yy0, mo0, dd0)
    end = datetime(yy1, mo1, dd1)
    if end < start:
        raise HTTPException(status_code=422, detail="to_date must be on or after from_date")
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _fetch_historical_day_payload(
    date: str,
    *,
    start: str,
    end: str,
    angel_interval: str,
    exchange: str,
    symboltoken: str,
) -> dict[str, Any] | None:
    yy, mo, dd = _parse_yyyy_mm_dd(date)
    sh, sm = _parse_start_hhmm(start)
    eh, em = _parse_start_hhmm(end)
    tz = _asia_kolkata_tz()
    from_dt = datetime(yy, mo, dd, sh, sm, 0, tzinfo=tz)
    to_dt = datetime(yy, mo, dd, eh, em, 0, tzinfo=tz)
    if to_dt <= from_dt:
        return None

    fromdate = from_dt.strftime("%Y-%m-%d %H:%M")
    todate = to_dt.strftime("%Y-%m-%d %H:%M")

    cache_key = f"{date}|{start}|{end}|{angel_interval}|{exchange}|{symboltoken}"
    mono = time.monotonic()
    cached = _HIST_DAY_CACHE.get(cache_key)
    if cached is not None and mono - cached[0] < _HIST_DAY_CACHE_TTL_SEC:
        return cached[1]
    if len(_HIST_DAY_CACHE) > _HIST_DAY_CACHE_MAX:
        cutoff = mono - _HIST_DAY_CACHE_TTL_SEC
        for k in [k for k, (t, _) in _HIST_DAY_CACHE.items() if t < cutoff]:
            _HIST_DAY_CACHE.pop(k, None)
        overflow = len(_HIST_DAY_CACHE) - _HIST_DAY_CACHE_MAX
        if overflow > 0:
            for k in sorted(_HIST_DAY_CACHE, key=lambda x: _HIST_DAY_CACHE[x][0])[:overflow]:
                _HIST_DAY_CACHE.pop(k, None)

    try:
        raw = post_get_candle_data(
            api_key=settings.angel_api_key.strip(),
            jwt_token=settings.angel_jwt_token.strip(),
            source_id=(settings.angel_source_id or "WEB").strip(),
            client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
            client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
            mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
            user_type=(settings.angel_user_type or "USER").strip(),
            exchange=exchange,
            symboltoken=symboltoken,
            interval=angel_interval,
            fromdate=fromdate,
            todate=todate,
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
        )
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError) as e:
        LOG.warning("Angel historical candles failed for %s: %s", date, e)
        _HIST_DAY_CACHE[cache_key] = (mono, None)
        return None

    rows = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), list) else []
    candles: list[dict[str, Any]] = []
    for row in rows:
        ct, o, h, l, c = _parse_candle_row(row)
        if ct is None or o is None or h is None or l is None or c is None:
            continue
        candles.append({"time": ct, "open": o, "high": h, "low": l, "close": c})

    if not candles:
        return None

    target = f"{sh:02d}:{sm:02d}"
    start_base = None
    for candle in candles:
        if target in str(candle["time"]).replace("T", " "):
            start_base = candle
            break
    if start_base is None:
        start_base = candles[0]

    base_close = start_base.get("close") if isinstance(start_base, dict) else None
    if base_close is None:
        _HIST_DAY_CACHE[cache_key] = (mono, None)
        return None

    payload = {
        "ok": True,
        "date": date,
        "start_time": f"{sh:02d}:{sm:02d}",
        "end_time": f"{eh:02d}:{em:02d}",
        "interval": angel_interval,
        "exchange": exchange,
        "symboltoken": symboltoken,
        "fromdate": fromdate,
        "todate": todate,
        "base_candle": start_base,
        "base": float(base_close),
        "candles": candles,
    }
    _HIST_DAY_CACHE[cache_key] = (mono, payload)
    return payload


def _fetch_latest_session_payload(
    *,
    start: str,
    end: str,
    angel_interval: str,
    exchange: str,
    symboltoken: str,
) -> dict[str, Any] | None:
    tz = _asia_kolkata_tz()
    today = datetime.now(tz).date()
    for offset in range(_LAST_SESSION_LOOKBACK_DAYS):
        day = today - timedelta(days=offset)
        payload = _fetch_historical_day_payload(
            day.strftime("%Y-%m-%d"),
            start=start,
            end=end,
            angel_interval=angel_interval,
            exchange=exchange,
            symboltoken=symboltoken,
        )
        if payload is not None:
            return payload
    return None


@router.get("/start-bar-close")
def angel_start_bar_close(start: str = "09:15", _user: User = Depends(get_current_user)):
    """
    Close of the first ONE_MINUTE candle at `start` (IST) for today, for the primary
    instrument in ANGEL_EXCHANGE_TOKENS (same token as live-quote).
    """
    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(
            status_code=503,
            detail="Angel One not configured: set ANGEL_API_KEY and ANGEL_JWT_TOKEN in backend/.env",
        )

    exchange_tokens = _parse_exchange_tokens(settings.angel_exchange_tokens)
    if not exchange_tokens:
        raise HTTPException(
            status_code=503,
            detail='Set ANGEL_EXCHANGE_TOKENS JSON, e.g. {"BSE":["99919000"]} for SENSEX',
        )

    hh, mm = _parse_start_hhmm(start)
    tz = _asia_kolkata_tz()
    now = datetime.now(tz)
    day = now.date()
    from_dt = datetime(day.year, day.month, day.day, hh, mm, 0, tzinfo=tz)
    to_dt = from_dt + timedelta(minutes=15)
    fromdate = from_dt.strftime("%Y-%m-%d %H:%M")
    todate = to_dt.strftime("%Y-%m-%d %H:%M")

    exchange = next(iter(exchange_tokens.keys()))
    tokens = exchange_tokens[exchange]
    if not tokens:
        raise HTTPException(status_code=503, detail="ANGEL_EXCHANGE_TOKENS has empty token list")
    symboltoken = tokens[0]

    cache_key = f"{exchange}:{symboltoken}:{fromdate}:{todate}"
    mono = time.monotonic()
    if (
        _START_BAR_CACHE["payload"] is not None
        and _START_BAR_CACHE["key"] == cache_key
        and mono - float(_START_BAR_CACHE["t"]) < _START_BAR_CACHE_TTL_SEC
    ):
        return _START_BAR_CACHE["payload"]

    try:
        raw = post_get_candle_data(
            api_key=settings.angel_api_key.strip(),
            jwt_token=settings.angel_jwt_token.strip(),
            source_id=(settings.angel_source_id or "WEB").strip(),
            client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
            client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
            mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
            user_type=(settings.angel_user_type or "USER").strip(),
            exchange=exchange,
            symboltoken=symboltoken,
            interval="ONE_MINUTE",
            fromdate=fromdate,
            todate=todate,
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
        )
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError) as e:
        LOG.warning("Angel start-bar-close failed: %s", e)
        out = {
            "ok": False,
            "start_time": f"{hh:02d}:{mm:02d}",
            "close": None,
            "candle_time": None,
            "open": None,
            "high": None,
            "low": None,
            "exchange": exchange,
            "symboltoken": symboltoken,
            "fromdate": fromdate,
            "todate": todate,
            "message": str(e),
            "as_of": time.time(),
        }
        _START_BAR_CACHE["t"] = mono
        _START_BAR_CACHE["key"] = cache_key
        _START_BAR_CACHE["payload"] = out
        return out

    msg = ""
    if isinstance(raw, dict):
        msg = str(raw.get("message") or raw.get("Message") or "")

    rows = None
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        rows = raw["data"]

    close_val: float | None = None
    open_val: float | None = None
    high_val: float | None = None
    low_val: float | None = None
    candle_time: str | None = None

    if rows:
        target_sub = f"{hh:02d}:{mm:02d}"
        chosen: tuple[str | None, float | None, float | None, float | None, float | None] | None = None
        chosen_fallback: tuple[str | None, float | None, float | None, float | None, float | None] | None = None
        for row in rows:
            ct, o, h, l, c = _parse_candle_row(row)
            if c is None:
                continue
            if chosen_fallback is None:
                chosen_fallback = (ct, o, h, l, c)
            tnorm = (ct or "").replace("T", " ")
            if target_sub in tnorm:
                chosen = (ct, o, h, l, c)
                break
        pick = chosen or chosen_fallback
        if pick:
            candle_time, open_val, high_val, low_val, close_val = pick

    out = {
        "ok": close_val is not None,
        "start_time": f"{hh:02d}:{mm:02d}",
        "close": close_val,
        "open": open_val,
        "high": high_val,
        "low": low_val,
        "candle_time": candle_time,
        "exchange": exchange,
        "symboltoken": symboltoken,
        "fromdate": fromdate,
        "todate": todate,
        "message": (msg or "") if close_val is None else "",
        "as_of": time.time(),
        "raw": raw if settings.angel_debug else None,
    }
    if close_val is None and not out["message"]:
        out["message"] = "No 1m candle in range (pre-open, holiday, or data not ready yet)"

    if close_val is None:
        fallback = _fetch_latest_session_payload(
            start=start,
            end="15:30",
            angel_interval="ONE_MINUTE",
            exchange=exchange,
            symboltoken=symboltoken,
        )
        if fallback is not None:
            fallback_candles = fallback.get("candles") if isinstance(fallback.get("candles"), list) else []
            last_candle = fallback_candles[-1] if fallback_candles else fallback.get("base_candle")
            if isinstance(last_candle, dict):
                out.update(
                    {
                        "ok": True,
                        "close": last_candle.get("close"),
                        "open": last_candle.get("open"),
                        "high": last_candle.get("high"),
                        "low": last_candle.get("low"),
                        "candle_time": last_candle.get("time"),
                        "date": fallback.get("date"),
                        "is_fallback": True,
                        "message": "Showing last available session close",
                    }
                )

    _START_BAR_CACHE["t"] = mono
    _START_BAR_CACHE["key"] = cache_key
    _START_BAR_CACHE["payload"] = out
    return out


@router.get("/historical-candles")
def angel_historical_candles(
    date: str = Query(..., description="Trading date in YYYY-MM-DD"),
    start: str = "09:15",
    end: str = "15:30",
    interval: str = "5",
    _user: User = Depends(get_current_user),
):
    """
    Historical candles for the primary SENSEX token configured in ANGEL_EXCHANGE_TOKENS.
    The frontend uses the candle at `start` as BASE for backtesting.
    """
    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(
            status_code=503,
            detail="Angel One not configured: set ANGEL_API_KEY and ANGEL_JWT_TOKEN in backend/.env",
        )

    interval_key = (interval or "5").strip().upper()
    angel_interval = _INTERVAL_MAP.get(interval_key)
    if not angel_interval:
        raise HTTPException(status_code=422, detail="Supported intervals: 1, 3, 5, 10, 15, 30, 60")

    exchange, symboltoken = _primary_exchange_token()
    payload = _fetch_historical_day_payload(
        date, start=start, end=end, angel_interval=angel_interval, exchange=exchange, symboltoken=symboltoken,
    )
    if payload is None:
        return {
            "ok": False,
            "date": date,
            "start_time": start,
            "end_time": end,
            "interval": angel_interval,
            "base_candle": None,
            "base": None,
            "candles": [],
            "message": "No candles found for selected date/time",
        }
    payload["message"] = ""
    return payload


_BATCH_MAX_DAYS = 366
_BATCH_WORKERS = 16


@router.get("/historical-candles-batch")
def angel_historical_candles_batch(
    from_date: str = Query(..., alias="from_date", description="Start date YYYY-MM-DD"),
    to_date: str = Query(..., alias="to_date", description="End date YYYY-MM-DD"),
    start: str = "09:15",
    end: str = "15:30",
    interval: str = "1",
    _user: User = Depends(get_current_user),
):
    """Parallel fetch of historical candles for backtest date ranges (up to 366 days)."""
    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise HTTPException(
            status_code=503,
            detail="Angel One not configured: set ANGEL_API_KEY and ANGEL_JWT_TOKEN in backend/.env",
        )

    interval_key = (interval or "1").strip().upper()
    angel_interval = _INTERVAL_MAP.get(interval_key)
    if not angel_interval:
        raise HTTPException(status_code=422, detail="Supported intervals: 1, 3, 5, 10, 15, 30, 60")

    dates = _iter_dates(from_date, to_date)
    if len(dates) > _BATCH_MAX_DAYS:
        raise HTTPException(status_code=422, detail=f"Maximum {_BATCH_MAX_DAYS} days per batch request")

    exchange, symboltoken = _primary_exchange_token()

    if len(dates) == 1:
        payloads = [
            _fetch_historical_day_payload(
                dates[0], start=start, end=end, angel_interval=angel_interval,
                exchange=exchange, symboltoken=symboltoken,
            ),
        ]
    else:
        workers = min(_BATCH_WORKERS, max(1, len(dates)))

        def _one(d: str) -> dict[str, Any] | None:
            return _fetch_historical_day_payload(
                d, start=start, end=end, angel_interval=angel_interval,
                exchange=exchange, symboltoken=symboltoken,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            payloads = list(pool.map(_one, dates))

    days = [p for p in payloads if p is not None]
    return {
        "ok": bool(days),
        "from_date": from_date,
        "to_date": to_date,
        "start_time": start,
        "end_time": end,
        "interval": angel_interval,
        "days_count": len(days),
        "skipped_count": len(dates) - len(days),
        "days": days,
        "message": "" if days else "No candles found for selected date range",
    }


@router.post("/refresh-session")
async def angel_refresh_session(_user: User = Depends(get_current_user)):
    """
    Run `scripts/angel_smartapi_login.py` with the backend venv, update ANGEL_JWT_TOKEN
    in `.env` and in-memory settings. Admin only. Does not replace the manual script workflow.
    """
    from app.services.angel_auto_login_scheduler import trigger_manual_angel_login_async

    return await trigger_manual_angel_login_async()
