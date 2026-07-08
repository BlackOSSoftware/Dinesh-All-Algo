"""Fetch MCX LTP quotes via Angel SmartAPI (LTP-only, never OHLC close)."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import BACKEND_ROOT, settings
from app.services.angel_quote import post_market_quote, _truthy_status
from app.services.mcx_instruments import McxInstrument, load_mcx_instruments

LOG = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, float, bool, str, str]] = {}
_CACHE_TTL_SEC = 0.5
_LTP_DISK_PATH = BACKEND_ROOT / "instance" / "mcx_last_ltp.json"

_LTP_KEYS = ("ltp", "LTP", "lastTradePrice", "lasttradeprice", "LastTradePrice", "lastPrice")
_PREV_CLOSE_KEYS = ("close", "Close", "prevClose", "previousClose", "PC")

_fetch_lock = threading.Lock()
_last_fetch_mono: float = 0.0
_last_results: list["QuoteResult"] = []
_last_token_login_mono: float = 0.0
_TOKEN_LOGIN_DEBOUNCE_SEC = 300.0


@dataclass
class QuoteResult:
    key: str
    label: str
    price: float
    market_open: bool
    source: str
    tradingsymbol: str
    price_type: str = "LTP"
    error: str | None = None


def _ist_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except ZoneInfoNotFoundError:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _mcx_session_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 23 * 60 + 30


def _angel_headers() -> dict[str, str]:
    return {
        "api_key": settings.angel_api_key.strip(),
        "jwt_token": settings.angel_jwt_token.strip(),
        "source_id": settings.angel_source_id,
        "client_local_ip": settings.angel_client_local_ip,
        "client_public_ip": settings.angel_client_public_ip,
        "mac_address": settings.angel_mac_address,
        "user_type": settings.angel_user_type,
    }


def _is_token_error_message(msg: str) -> bool:
    t = (msg or "").lower()
    return "invalid token" in t or "tokenexception" in t or "token is invalid" in t


def _maybe_refresh_angel_session(*, reason: str) -> bool:
    """Try refresh-token exchange, then full TOTP login. Debounced for full login."""
    global _last_token_login_mono

    from app.services.angel_jwt_refresh import try_refresh_angel_jwt_via_refresh_token

    if try_refresh_angel_jwt_via_refresh_token(reason=reason, force=True):
        return True

    now = time.monotonic()
    if now - _last_token_login_mono < _TOKEN_LOGIN_DEBOUNCE_SEC:
        return False
    _last_token_login_mono = now

    try:
        from app.services.angel_auto_login_scheduler import (
            apply_jwt_from_script_output,
            run_angel_smartapi_login_subprocess,
        )

        ok, stdout, _stderr, _rc = run_angel_smartapi_login_subprocess(reason=reason)
        if ok and apply_jwt_from_script_output(stdout):
            LOG.info("Angel session restored via TOTP login (%s)", reason)
            return True
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Angel TOTP login failed (%s): %s", reason, exc)
    return False


def _pick_float(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in row:
            continue
        raw = row[key]
        if raw is None or raw == "":
            continue
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            continue
    return None


def _row_token(row: dict[str, Any]) -> str:
    return str(row.get("symbolToken") or row.get("symboltoken") or row.get("token") or "").strip()


def _parse_fetched_row(row: dict[str, Any]) -> tuple[float | None, float | None, str]:
    """Return (ltp, prev_close, price_type_used)."""
    ltp = _pick_float(row, _LTP_KEYS)
    prev_close = _pick_float(row, _PREV_CLOSE_KEYS)
    if ltp is not None:
        return ltp, prev_close, "LTP"
    if prev_close is not None:
        return prev_close, prev_close, "CLOSE"
    return None, None, "LTP"


def _load_disk_ltp() -> dict[str, float]:
    if not _LTP_DISK_PATH.is_file():
        return {}
    try:
        data = json.loads(_LTP_DISK_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items() if v}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _save_disk_ltp(key: str, price: float) -> None:
    if price <= 0:
        return
    data = _load_disk_ltp()
    data[key] = price
    _LTP_DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LTP_DISK_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _quote_mode() -> str:
    mode = (settings.angel_quote_mode or "LTP").strip().upper()
    return mode if mode in ("LTP", "OHLC", "FULL") else "LTP"


def _fetch_batch_quotes(
    instruments: list[McxInstrument],
    *,
    _retry_depth: int = 0,
) -> dict[str, tuple[float, str, str]]:
    """Fetch all configured MCX instruments in one Angel quote request. Returns key -> (price, price_type, source)."""
    exchange_tokens: dict[str, list[str]] = {}
    token_to_keys: dict[str, list[str]] = {}
    seen_tokens: set[str] = set()
    for inst in instruments:
        if not inst.configured:
            continue
        keys = token_to_keys.setdefault(inst.token, [])
        if inst.key not in keys:
            keys.append(inst.key)
        if inst.token not in seen_tokens:
            exchange_tokens.setdefault(inst.exchange, []).append(inst.token)
            seen_tokens.add(inst.token)

    if not exchange_tokens:
        return {}

    raw = post_market_quote(
        mode=_quote_mode(),
        exchange_tokens=exchange_tokens,
        timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
        **_angel_headers(),
    )
    if not _truthy_status(raw):
        msg = str(raw.get("message") or raw.get("errorcode") or raw.get("errorCode") or "Angel quote failed")
        if _is_token_error_message(msg) and _retry_depth < 1 and _maybe_refresh_angel_session(reason="mcx_quote_token"):
            return _fetch_batch_quotes(instruments, _retry_depth=_retry_depth + 1)
        raise RuntimeError(msg)

    data = raw.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Empty Angel quote data")

    rows: list[dict[str, Any]] = []
    fetched = data.get("fetched")
    if isinstance(fetched, list):
        rows.extend(r for r in fetched if isinstance(r, dict))

    out: dict[str, tuple[float, str, str]] = {}
    for row in rows:
        token = _row_token(row)
        keys = token_to_keys.get(token) or []
        if not keys:
            continue
        ltp, _, price_type = _parse_fetched_row(row)
        if ltp is not None:
            for key in keys:
                out[key] = (ltp, price_type, "live")

    if not out and rows:
        for inst in instruments:
            if not inst.configured:
                continue
            for row in rows:
                ltp, _, price_type = _parse_fetched_row(row)
                if ltp is not None:
                    out[inst.key] = (ltp, price_type, "live")
                    break

    if not out:
        raise RuntimeError("No LTP in Angel response")
    return out


def _quote_from_cache(key: str, instrument: McxInstrument, *, error: str | None = None) -> QuoteResult:
    mem = _CACHE.get(key)
    disk = _load_disk_ltp().get(key, 0.0)
    price = mem[0] if mem and mem[0] > 0 else disk
    price_type = mem[4] if mem and len(mem) > 4 else ("LTP" if price > 0 else "LTP")
    source = "last" if price > 0 else "unconfigured"
    return QuoteResult(
        key=key,
        label=instrument.label,
        price=price,
        market_open=False,
        source=source,
        tradingsymbol=instrument.tradingsymbol,
        price_type=price_type,
        error=error if price <= 0 else None,
    )


def _store_quote(key: str, price: float, source: str, market_open: bool, price_type: str) -> None:
    _CACHE[key] = (price, time.monotonic(), market_open, source, price_type)
    _save_disk_ltp(key, price)


def _build_result(
    key: str,
    instrument: McxInstrument,
    price: float,
    source: str,
    price_type: str,
) -> QuoteResult:
    session_open = _mcx_session_open()
    live = source == "live" and price_type == "LTP" and session_open
    return QuoteResult(
        key=key,
        label=instrument.label,
        price=price,
        market_open=live,
        source="live" if live else ("last" if price > 0 else source),
        tradingsymbol=instrument.tradingsymbol,
        price_type=price_type,
    )


def _results_from_memory_cache(instruments: list[McxInstrument], now: float) -> list[QuoteResult] | None:
    configured = [inst for inst in instruments if inst.configured]
    if not configured:
        return None
    if not all(
        (cached := _CACHE.get(inst.key)) and (now - cached[1]) < _CACHE_TTL_SEC for inst in configured
    ):
        return None
    return [
        QuoteResult(
            key=inst.key,
            label=inst.label,
            price=_CACHE[inst.key][0],
            market_open=_CACHE[inst.key][2],
            source=_CACHE[inst.key][3],
            tradingsymbol=inst.tradingsymbol,
            price_type=_CACHE[inst.key][4] if len(_CACHE[inst.key]) > 4 else "LTP",
        )
        for inst in instruments
        if inst.configured and inst.key in _CACHE
    ] + [
        _quote_from_cache(inst.key, inst, error="Could not resolve MCX token — check Angel login")
        for inst in instruments
        if not inst.configured
    ]


def _fetch_all_mcx_quotes_locked() -> list[QuoteResult]:
    global _last_fetch_mono, _last_results

    instruments = list(load_mcx_instruments().values())
    if not instruments:
        return []

    now = time.monotonic()
    cached = _results_from_memory_cache(instruments, now)
    if cached is not None:
        return cached

    if _last_results and (now - _last_fetch_mono) < _CACHE_TTL_SEC:
        return list(_last_results)

    results: list[QuoteResult] = []
    configured = [inst for inst in instruments if inst.configured]

    if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
        for inst in instruments:
            err = "Could not resolve MCX token" if not inst.configured else "Angel JWT not configured"
            results.append(_quote_from_cache(inst.key, inst, error=err))
        _last_results = results
        _last_fetch_mono = now
        return results

    for inst in instruments:
        if not inst.configured:
            results.append(
                _quote_from_cache(
                    inst.key,
                    inst,
                    error="Could not resolve MCX token — check Angel login",
                )
            )

    if configured:
        try:
            batch = _fetch_batch_quotes(configured)
            session_open = _mcx_session_open()
            for inst in configured:
                if inst.key not in batch:
                    results.append(_quote_from_cache(inst.key, inst, error="No LTP in Angel response"))
                    continue
                price, price_type, source = batch[inst.key]
                _store_quote(inst.key, price, source, session_open, price_type)
                results.append(_build_result(inst.key, inst, price, source, price_type))
                LOG.debug("MCX %s %s %s=%.2f", inst.key, inst.tradingsymbol, price_type, price)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("MCX batch quote failed: %s", exc)
            for inst in configured:
                cached_row = _quote_from_cache(inst.key, inst, error=str(exc)[:160])
                results.append(cached_row)

    order = {inst.key: i for i, inst in enumerate(instruments)}
    results.sort(key=lambda r: order.get(r.key, 999))
    _last_results = results
    _last_fetch_mono = now
    return results


def ensure_angel_session_for_quotes(*, reason: str = "ensure_session") -> bool:
    """Public helper: restore Angel JWT when quotes need a valid session."""
    return _maybe_refresh_angel_session(reason=reason)


def fetch_all_mcx_quotes() -> list[QuoteResult]:
    with _fetch_lock:
        return _fetch_all_mcx_quotes_locked()


def quote_from_results(results: list[QuoteResult], key: str) -> QuoteResult | None:
    k = (key or "").upper()
    for q in results:
        if q.key == k:
            return q
    return None


def fetch_instrument_ltp(instrument: McxInstrument) -> QuoteResult:
    q = quote_from_results(fetch_all_mcx_quotes(), instrument.key)
    if q:
        return q
    return _quote_from_cache(instrument.key, instrument, error="Quote unavailable")


def get_quote_by_key(key: str) -> QuoteResult | None:
    results = fetch_all_mcx_quotes()
    q = quote_from_results(results, key)
    if q:
        return q
    inst = load_mcx_instruments().get((key or "").upper())
    if not inst:
        return None
    return fetch_instrument_ltp(inst)
