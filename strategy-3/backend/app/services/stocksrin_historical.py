"""StocksRin historical option & index chart API (via session-managed client)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.services.stocksrin.api_client import get_api_client
from app.services.stocksrin.response_interceptor import SESSION_EXPIRED_MSG, user_facing_auth_error
from app.services.stocksrin.session_manager import StocksRinAuthError, get_session_manager

LOG = logging.getLogger(__name__)

_OPTION_PATH = "/history/data/historical/option/chart"
_SPOT_PATH = "/history/data/historical/spot/chart"

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL_SEC = 3600.0
_CACHE_MAX = 512


@dataclass
class StocksRinFetchResult:
    ok: bool = False
    candles: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    api_status: str | None = None
    raw: Any = None
    request: dict[str, Any] = field(default_factory=dict)
    auth_error: bool = False


def _ist_tz():
    try:
        return ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=5, minutes=30))


def unix_to_ist_iso(ts: int | float) -> str:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(_ist_tz())
    return dt.isoformat(timespec="seconds")


def session_unix_range(date: str, *, start_hhmm: str = "09:15", end_hhmm: str = "15:30") -> tuple[int, int]:
    yy, mo, dd = int(date[0:4]), int(date[5:7]), int(date[8:10])
    tz = _ist_tz()

    def _to_unix(hhmm: str) -> int:
        h, m = (int(x) for x in hhmm.split(":"))
        return int(datetime(yy, mo, dd, h, m, 0, tzinfo=tz).timestamp())

    return _to_unix(start_hhmm), _to_unix(end_hhmm)


def parse_csv_candle_row(row: str) -> dict[str, Any] | None:
    s = (row or "").strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    if len(parts) < 6:
        return None
    try:
        ts = int(float(parts[0]))
        o, h, l, c = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        vol = float(parts[5]) if len(parts) > 5 else 0.0
        oi = float(parts[6]) if len(parts) > 6 else 0.0
    except (TypeError, ValueError):
        return None
    return {
        "timestamp": ts,
        "time": unix_to_ist_iso(ts),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": vol,
        "oi": oi,
    }


def parse_chart_data(data: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if data is None:
        return out
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if isinstance(row, str):
            parsed = parse_csv_candle_row(row)
            if parsed:
                out.append(parsed)
        elif isinstance(row, dict):
            ts = row.get("timestamp") or row.get("time")
            if ts is None:
                continue
            try:
                ts_i = int(ts) if not isinstance(ts, str) or ts.isdigit() else int(float(ts))
            except (TypeError, ValueError):
                continue
            out.append({
                "timestamp": ts_i,
                "time": unix_to_ist_iso(ts_i),
                "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0),
                "low": float(row.get("low") or 0),
                "close": float(row.get("close") or 0),
                "volume": float(row.get("volume") or 0),
                "oi": float(row.get("oi") or 0),
            })
    out.sort(key=lambda x: x["timestamp"])
    return out


def stocksRin_configured() -> bool:
    mgr = get_session_manager()
    if not mgr.is_configured():
        mgr.load()
    return mgr.is_configured()


def get_auth_debug() -> dict[str, Any]:
    return get_session_manager().stats.to_debug_dict()


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    hit = _CACHE.get(key)
    if not hit:
        return None
    if time.monotonic() - hit[0] > _CACHE_TTL_SEC:
        _CACHE.pop(key, None)
        return None
    return hit[1]


def _cache_put(key: str, candles: list[dict[str, Any]]) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (time.monotonic(), candles)


def _fetch_chart(*, path: str, params: dict[str, Any], cache_key: str) -> StocksRinFetchResult:
    req_meta: dict[str, Any] = {"path": path, **params}
    cached = _cache_get(cache_key)
    if cached is not None:
        LOG.info("Historical Data Loaded: %d candles (cache)", len(cached))
        return StocksRinFetchResult(ok=True, candles=cached, request={**req_meta, "cached": True})

    client = get_api_client()
    try:
        status, raw, meta = client.get(path, params)
        req_meta.update(meta)
    except StocksRinAuthError as exc:
        LOG.error("StocksRin auth failed: %s", exc)
        return StocksRinFetchResult(
            ok=False,
            error=str(exc),
            api_status="auth_failed",
            request=req_meta,
            auth_error=True,
        )
    except RuntimeError as exc:
        return StocksRinFetchResult(ok=False, error=str(exc), request=req_meta)

    api_status = str(raw.get("status") or raw.get("Status") or "").strip() if isinstance(raw, dict) else ""
    data = raw.get("data") if isinstance(raw, dict) else None

    if api_status and api_status.lower() not in ("success", "ok", ""):
        return StocksRinFetchResult(
            ok=False,
            error=f"API status={api_status}",
            api_status=api_status,
            raw=raw,
            request=req_meta,
        )

    if data is None:
        return StocksRinFetchResult(
            ok=False,
            error="API returned data=null",
            api_status=api_status or "null_data",
            raw=raw,
            request=req_meta,
        )

    candles = parse_chart_data(data)
    LOG.info("Historical Data Loaded: %d candles | status=%s", len(candles), api_status or status)
    if not candles:
        return StocksRinFetchResult(
            ok=False,
            error="No candles parsed from API response",
            api_status=api_status or "empty",
            raw=raw,
            request=req_meta,
        )

    _cache_put(cache_key, candles)
    return StocksRinFetchResult(
        ok=True,
        candles=candles,
        api_status=api_status or "success",
        raw=raw,
        request=req_meta,
    )


def fetch_index_candles(
    date: str,
    *,
    resolution: int | str | None = None,
    start_hhmm: str = "09:15",
    end_hhmm: str = "15:30",
) -> StocksRinFetchResult:
    from_ts, to_ts = session_unix_range(date, start_hhmm=start_hhmm, end_hhmm=end_hhmm)
    res = str(resolution or settings.stocksrin_resolution or 10)
    symbol = (settings.stocksrin_index_symbol or "SENSEX").strip()
    exchange = (settings.stocksrin_index_exchange or "BSE").strip()
    cache_key = f"spot|{symbol}|{exchange}|{res}|{from_ts}|{to_ts}"
    params = {
        "symbol": symbol,
        "from": from_ts,
        "to": to_ts,
        "resolution": res,
        "exchange": exchange,
    }
    return _fetch_chart(path=_SPOT_PATH, params=params, cache_key=cache_key)


def fetch_option_candles(
    *,
    date: str,
    expiry: str,
    strike: float,
    option_type: str,
    resolution: int | str | None = None,
    start_hhmm: str = "09:15",
    end_hhmm: str = "15:30",
) -> StocksRinFetchResult:
    from_ts, to_ts = session_unix_range(date, start_hhmm=start_hhmm, end_hhmm=end_hhmm)
    res = str(resolution or settings.stocksrin_resolution or 10)
    index = (settings.stocksrin_index_symbol or "SENSEX").strip()
    exchange = (settings.stocksrin_exchange or "NSE").strip()
    side = option_type.strip().upper()
    strike_i = int(strike) if strike == int(strike) else strike
    cache_key = f"opt|{expiry}|{strike_i}|{side}|{res}|{from_ts}|{to_ts}|{exchange}"
    params = {
        "index": index,
        "strike": strike_i,
        "optiontype": side,
        "expiry": expiry[:10],
        "from": from_ts,
        "to": to_ts,
        "resolution": res,
        "exchange": exchange,
    }
    return _fetch_chart(path=_OPTION_PATH, params=params, cache_key=cache_key)


def clear_cache() -> None:
    _CACHE.clear()
