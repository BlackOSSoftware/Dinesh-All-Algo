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
from app.services.mcx_scrip_resolver import tradingsymbol_is_expired

LOG = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, float, bool, str, str]] = {}
# One Angel batch call covers all MCX symbols. Cross-process shared cache (S2+S4)
# plus a global Angel gate keep us under Angel's ~1 req/s budget.
_CACHE_TTL_SEC = 1.5
_ENGINE_CACHE_TTL_SEC = 1.2
_SOFT_HOLD_SEC = 4.0
_LTP_DISK_PATH = BACKEND_ROOT / "instance" / "mcx_last_ltp.json"

_LTP_KEYS = ("ltp", "LTP", "lastTradePrice", "lasttradeprice", "LastTradePrice", "lastPrice")
_PREV_CLOSE_KEYS = ("close", "Close", "prevClose", "previousClose", "PC")

_fetch_lock = threading.Lock()
_last_fetch_mono: float = 0.0
_last_results: list["QuoteResult"] = []
_last_token_login_mono: float = 0.0
_TOKEN_LOGIN_DEBOUNCE_SEC = 300.0
_last_runtime_jwt: str = ""


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
    return (
        "invalid token" in t
        or "tokenexception" in t
        or "token is invalid" in t
        or "ag8001" in t
        or ("jwt" in t and "expired" in t)
    )


def _maybe_refresh_angel_session(*, reason: str) -> bool:
    """Auto-heal Angel session: env reload → validate → refresh token → TOTP script."""
    from app.services.angel_jwt_refresh import ensure_valid_angel_session

    try:
        return ensure_valid_angel_session(reason=reason)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Angel session auto-heal failed (%s): %s", reason, exc)
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

    try:
        raw = post_market_quote(
            mode=_quote_mode(),
            exchange_tokens=exchange_tokens,
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
            **_angel_headers(),
        )
    except RuntimeError as exc:
        # HTTP 403 token rejection whose internal refresh retry failed — full heal + one retry.
        if _is_token_error_message(str(exc)) and _retry_depth < 1 and _maybe_refresh_angel_session(reason="mcx_quote_http_token"):
            return _fetch_batch_quotes(instruments, _retry_depth=_retry_depth + 1)
        raise
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
    # Keep Angel/token errors even when a stale disk price exists, so Generate Token can show.
    return QuoteResult(
        key=key,
        label=instrument.label,
        price=price,
        market_open=_mcx_session_open(),
        source=source,
        tradingsymbol=instrument.tradingsymbol,
        price_type=price_type,
        error=error,
    )


def _store_quote(key: str, price: float, source: str, market_open: bool, price_type: str) -> None:
    _CACHE[key] = (price, time.monotonic(), market_open, source, price_type)
    _save_disk_ltp(key, price)


def clear_mcx_quote_cache() -> None:
    global _CACHE, _last_fetch_mono, _last_results, _last_runtime_jwt, _last_token_login_mono
    _CACHE = {}
    _last_fetch_mono = 0.0
    _last_results = []
    _last_runtime_jwt = (settings.angel_jwt_token or "").strip()
    _last_token_login_mono = 0.0


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
        # Session window is independent of whether Angel LTP succeeded.
        market_open=session_open,
        source="live" if live else ("last" if price > 0 else source),
        tradingsymbol=instrument.tradingsymbol,
        price_type=price_type,
    )


def _results_from_soft_hold(instruments: list[McxInstrument], now: float) -> list[QuoteResult] | None:
    """Keep showing last successful live quotes briefly during Angel cooldown."""
    configured = [inst for inst in instruments if inst.configured]
    if not configured:
        return None
    if not all(
        (cached := _CACHE.get(inst.key))
        and cached[0] > 0
        and (now - cached[1]) < _SOFT_HOLD_SEC
        for inst in configured
    ):
        return None
    out: list[QuoteResult] = []
    for inst in instruments:
        if not inst.configured:
            out.append(
                _quote_from_cache(
                    inst.key,
                    inst,
                    error="Could not resolve MCX token - check Angel login",
                )
            )
            continue
        c = _CACHE[inst.key]
        src = c[3] if c[3] in ("live", "last") else "last"
        out.append(
            QuoteResult(
                key=inst.key,
                label=inst.label,
                price=c[0],
                market_open=c[2],
                source=src,
                tradingsymbol=inst.tradingsymbol,
                price_type=c[4] if len(c) > 4 else "LTP",
                error=None,
            )
        )
    return out


def _hydrate_from_shared(
    instruments: list[McxInstrument],
    shared: dict[str, dict[str, Any]],
) -> list[QuoteResult] | None:
    configured = [inst for inst in instruments if inst.configured]
    if not configured:
        return None
    if not all(inst.key in shared for inst in configured):
        return None
    results: list[QuoteResult] = []
    for inst in instruments:
        if not inst.configured:
            results.append(
                _quote_from_cache(
                    inst.key,
                    inst,
                    error="Could not resolve MCX token - check Angel login",
                )
            )
            continue
        row = shared[inst.key]
        price = float(row.get("price") or 0)
        price_type = str(row.get("price_type") or "LTP")
        source = str(row.get("source") or "live")
        built = _build_result(inst.key, inst, price, source, price_type)
        _store_quote(inst.key, built.price, built.source, built.market_open, built.price_type)
        results.append(built)
    return results


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
        _quote_from_cache(inst.key, inst, error="Could not resolve MCX token - check Angel login")
        for inst in instruments
        if not inst.configured
    ]


def _fetch_all_mcx_quotes_locked() -> list[QuoteResult]:
    global _last_fetch_mono, _last_results, _last_runtime_jwt

    from app.services.angel_jwt_refresh import reload_angel_tokens_from_env
    from app.services.angel_upstream_gate import angel_rate_limit_remaining
    from app.services.mcx_shared_ltp import load_shared_mcx_batch, save_shared_mcx_batch

    changed = reload_angel_tokens_from_env()
    current_jwt = (settings.angel_jwt_token or "").strip()
    if changed or current_jwt != _last_runtime_jwt:
        clear_mcx_quote_cache()

    instruments = list(load_mcx_instruments().values())
    if not instruments:
        return []

    now = time.monotonic()
    cached = _results_from_memory_cache(instruments, now)
    if cached is not None:
        return cached

    if _last_results and (now - _last_fetch_mono) < _CACHE_TTL_SEC:
        return list(_last_results)

    # Prefer sibling strategy's fresh Angel batch before another upstream call.
    shared = load_shared_mcx_batch(max_age_sec=_CACHE_TTL_SEC)
    if shared:
        hydrated = _hydrate_from_shared(instruments, shared)
        if hydrated is not None:
            LOG.debug("MCX quotes served from shared cross-process cache")
            _last_results = hydrated
            _last_fetch_mono = now
            return hydrated

    # During rate-limit cooldown, soft-hold last live prices (no Angel call, no banner).
    if angel_rate_limit_remaining() > 0:
        soft = _results_from_soft_hold(instruments, now)
        if soft is not None:
            _last_results = soft
            _last_fetch_mono = now
            return soft
        shared_any = load_shared_mcx_batch(max_age_sec=30.0)
        if shared_any:
            hydrated = _hydrate_from_shared(instruments, shared_any)
            if hydrated is not None:
                # Age > TTL → mark as last so UI is honest, but omit rate-limit error spam.
                marked = [
                    QuoteResult(
                        key=r.key,
                        label=r.label,
                        price=r.price,
                        market_open=r.market_open,
                        source="last" if r.price > 0 else r.source,
                        tradingsymbol=r.tradingsymbol,
                        price_type=r.price_type,
                        error=None,
                    )
                    for r in hydrated
                ]
                _last_results = marked
                _last_fetch_mono = now
                return marked

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
                    error="Could not resolve MCX token - check Angel login",
                )
            )

    if configured:
        try:
            batch = _fetch_batch_quotes(configured)
            shared_payload: dict[str, dict[str, Any]] = {}
            for inst in configured:
                if inst.key not in batch:
                    err = "No LTP in Angel response"
                    if tradingsymbol_is_expired(inst.tradingsymbol):
                        from app.services.mcx_scrip_resolver import resolve_mcx_instrument

                        resolved = resolve_mcx_instrument(inst.key, allow_slow=True)
                        if resolved and resolved.get("token"):
                            try:
                                retry_batch = _fetch_batch_quotes(
                                    [
                                        McxInstrument(
                                            key=inst.key,
                                            label=resolved.get("label") or inst.label,
                                            exchange=resolved.get("exchange") or "MCX",
                                            token=str(resolved.get("token") or ""),
                                            tradingsymbol=str(resolved.get("tradingsymbol") or ""),
                                            lotsize=max(1, int(resolved.get("lotsize") or inst.lotsize)),
                                        )
                                    ]
                                )
                                if inst.key in retry_batch:
                                    price, price_type, source = retry_batch[inst.key]
                                    built = _build_result(inst.key, inst, price, source, price_type)
                                    _store_quote(inst.key, built.price, built.source, built.market_open, built.price_type)
                                    results.append(built)
                                    shared_payload[inst.key] = {
                                        "price": built.price,
                                        "price_type": built.price_type,
                                        "source": "live",
                                        "tradingsymbol": inst.tradingsymbol,
                                        "market_open": built.market_open,
                                    }
                                    LOG.info(
                                        "MCX %s re-resolved after expiry → %s",
                                        inst.key,
                                        resolved.get("tradingsymbol"),
                                    )
                                    continue
                            except Exception as retry_exc:  # noqa: BLE001
                                err = str(retry_exc)[:160]
                    results.append(_quote_from_cache(inst.key, inst, error=err))
                    continue
                price, price_type, source = batch[inst.key]
                built = _build_result(inst.key, inst, price, source, price_type)
                _store_quote(inst.key, built.price, built.source, built.market_open, built.price_type)
                results.append(built)
                shared_payload[inst.key] = {
                    "price": built.price,
                    "price_type": built.price_type,
                    "source": "live",
                    "tradingsymbol": inst.tradingsymbol,
                    "market_open": built.market_open,
                }
                LOG.debug("MCX %s %s %s=%.2f", inst.key, inst.tradingsymbol, price_type, price)
            if shared_payload:
                save_shared_mcx_batch(shared_payload)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("MCX batch quote failed: %s", exc)
            err_text = str(exc)
            rate_hit = (
                "access rate" in err_text.lower()
                or "exceeding" in err_text.lower()
                or "cooldown" in err_text.lower()
                or "backoff" in err_text.lower()
            )
            if rate_hit:
                soft = _results_from_soft_hold(instruments, time.monotonic())
                if soft is not None:
                    order = {inst.key: i for i, inst in enumerate(instruments)}
                    soft.sort(key=lambda r: order.get(r.key, 999))
                    _last_results = soft
                    _last_fetch_mono = now
                    return soft
                # Transient — show last price WITHOUT rate-limit banner spam.
                for inst in configured:
                    results.append(_quote_from_cache(inst.key, inst, error=None))
            else:
                for inst in configured:
                    results.append(_quote_from_cache(inst.key, inst, error=err_text[:160]))

    order = {inst.key: i for i, inst in enumerate(instruments)}
    results.sort(key=lambda r: order.get(r.key, 999))
    _last_results = results
    _last_fetch_mono = now
    return results


def ensure_angel_session_for_quotes(*, reason: str = "ensure_session") -> bool:
    """Public helper: restore Angel JWT when quotes need a valid session."""
    return _maybe_refresh_angel_session(reason=reason)


def fetch_all_mcx_quotes() -> list[QuoteResult]:
    # Fast path: serve memory cache without waiting on an in-flight Angel fetch.
    try:
        instruments = list(load_mcx_instruments().values())
        now = time.monotonic()
        cached = _results_from_memory_cache(instruments, now)
        if cached is not None:
            return cached
        if _last_results and (now - _last_fetch_mono) < _CACHE_TTL_SEC:
            return list(_last_results)
    except Exception:  # noqa: BLE001
        pass
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


def get_quote_by_key(key: str, *, engine: bool = False) -> QuoteResult | None:
    """Return MCX quote. engine=True uses a shorter cache TTL for the trading loop."""
    if engine:
        now = time.monotonic()
        k = (key or "").upper()
        cached = _CACHE.get(k)
        if cached and (now - cached[1]) < _ENGINE_CACHE_TTL_SEC and cached[0] > 0:
            inst = load_mcx_instruments().get(k)
            if inst:
                return QuoteResult(
                    key=k,
                    label=inst.label,
                    price=cached[0],
                    market_open=cached[2],
                    source=cached[3],
                    tradingsymbol=inst.tradingsymbol,
                    price_type=cached[4] if len(cached) > 4 else "LTP",
                )
    results = fetch_all_mcx_quotes()
    q = quote_from_results(results, key)
    if q:
        return q
    inst = load_mcx_instruments().get((key or "").upper())
    if not inst:
        return None
    return fetch_instrument_ltp(inst)
