"""
Shared SENSEX index LTP for trading engine + dashboard.

Single writer to Angel quote API (via sensex_quote token heal). Dashboard reads
the same in-memory cache so UI and engine stay in sync without double rate-limit hits.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings

LOG = logging.getLogger(__name__)

# Soft hold last *live* LTP briefly so a one-shot Angel blip does not skip engine ticks.
_SOFT_LIVE_HOLD_SEC = 4.0

_CACHE: dict[str, Any] = {
    "t": 0.0,
    "live_t": 0.0,
    "ltp": None,
    "prev_ltp": None,
    "detail": None,
    "ok": False,
    "payload": None,
}


def _parse_exchange_tokens(raw: str) -> dict[str, list[str]]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for ex, tokens in data.items():
        if not isinstance(ex, str):
            continue
        if isinstance(tokens, list):
            out[ex.upper()] = [str(t).strip() for t in tokens if str(t).strip()]
        elif isinstance(tokens, str) and tokens.strip():
            out[ex.upper()] = [tokens.strip()]
    return out


def _price_from_payload(payload: dict[str, Any]) -> tuple[float | None, str, str]:
    fetched = payload.get("fetched") if isinstance(payload, dict) else None
    row = fetched[0] if isinstance(fetched, list) and fetched and isinstance(fetched[0], dict) else None
    if not row:
        return None, str(payload.get("quote_source") or ""), str(payload.get("angel_message") or "")
    for k in ("ltp", "Ltp", "lasttradedprice", "lastTradePrice", "lastPrice", "close", "Close"):
        raw = row.get(k)
        if raw is None or raw == "":
            continue
        try:
            val = float(raw)
            if val > 0:
                return val, str(payload.get("quote_source") or "live"), str(payload.get("angel_message") or "")
        except (TypeError, ValueError):
            continue
    return None, str(payload.get("quote_source") or ""), str(payload.get("angel_message") or "")


def _fetch_live_payload() -> dict[str, Any]:
    from app.services.sensex_quote import fetch_sensex_live_quote

    exchange_tokens = _parse_exchange_tokens(settings.angel_exchange_tokens)
    if not exchange_tokens:
        exchange_tokens = {"BSE": ["99919000"]}
    mode = (settings.angel_quote_mode or "LTP").strip().upper()
    if mode not in ("LTP", "OHLC", "FULL"):
        mode = "LTP"
    return fetch_sensex_live_quote(exchange_tokens=exchange_tokens, mode=mode)


def _store_payload(payload: dict[str, Any], *, now: float | None = None) -> tuple[float | None, str, bool]:
    """Update shared cache from a sensex_quote payload. ok=True only for live Angel LTP."""
    now = time.monotonic() if now is None else now
    price, source, detail = _price_from_payload(payload)
    live_ok = bool(price is not None and source == "live" and payload.get("angel_ok"))

    if live_ok:
        prev = _CACHE.get("ltp")
        if prev is not None and float(prev) != float(price):
            _CACHE["prev_ltp"] = float(prev)
        _CACHE.update(
            {
                "t": now,
                "live_t": now,
                "ltp": float(price),
                "detail": detail or "",
                "ok": True,
                "payload": payload,
            }
        )
        return float(price), detail or "", True

    # Keep last good live LTP briefly (engine must not trade on disk/stale alone).
    last_live = _CACHE.get("ltp")
    live_age = now - float(_CACHE.get("live_t") or 0.0)
    if last_live is not None and live_age <= _SOFT_LIVE_HOLD_SEC and bool(_CACHE.get("ok")):
        _CACHE["t"] = now
        _CACHE["payload"] = payload if payload.get("quote_source") == "live" else _CACHE.get("payload")
        _CACHE["detail"] = detail or str(_CACHE.get("detail") or "holding last live LTP")
        return float(last_live), str(_CACHE["detail"]), True

    _CACHE.update(
        {
            "t": now,
            "ltp": float(price) if price is not None else _CACHE.get("ltp"),
            "detail": detail or "No live SENSEX LTP",
            "ok": False,
            "payload": payload,
        }
    )
    return (float(price) if price is not None else None), str(_CACHE["detail"]), False


def peek_shared_quote_payload(*, max_age_sec: float = 1.25) -> dict[str, Any] | None:
    """Dashboard/API: return cached quote payload if fresh enough (no Angel call)."""
    payload = _CACHE.get("payload")
    if not isinstance(payload, dict):
        return None
    age = time.monotonic() - float(_CACHE.get("t") or 0.0)
    if age > max_age_sec:
        return None
    if _CACHE.get("ltp") is None:
        return None
    return payload


def get_index_ltp_cached(ttl_sec: float = 1.0) -> tuple[float | None, str | None, bool]:
    """
    Returns (ltp, detail_message, market_ok).

    market_ok is True only for a fresh/soft-held *live* Angel quote — never disk.
    """
    ltp, detail, ok, _prev, _cache_hit = get_engine_tick_ltp(ttl_sec=ttl_sec)
    return ltp, detail, ok


def get_engine_tick_ltp(
    ttl_sec: float = 1.0,
) -> tuple[float | None, str | None, bool, float | None, bool]:
    """
    Engine tick LTP with previous sample for cross detection.
    Returns (ltp, detail, market_ok, prev_ltp, cache_hit).
    """
    now = time.monotonic()
    if (
        _CACHE["ltp"] is not None
        and bool(_CACHE["ok"])
        and now - float(_CACHE["t"]) < ttl_sec
    ):
        return (
            float(_CACHE["ltp"]),
            str(_CACHE["detail"] or ""),
            True,
            (_CACHE["prev_ltp"] if _CACHE.get("prev_ltp") is not None else None),
            True,
        )

    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        _CACHE.update({"t": now, "ltp": None, "detail": "Angel not configured", "ok": False, "payload": None})
        return None, "Angel not configured", False, None, False

    try:
        payload = _fetch_live_payload()
    except Exception as e:  # noqa: BLE001
        LOG.warning("market_ltp quote failed: %s", e)
        live_age = now - float(_CACHE.get("live_t") or 0.0)
        if _CACHE.get("ltp") is not None and bool(_CACHE.get("ok")) and live_age <= _SOFT_LIVE_HOLD_SEC:
            _CACHE["t"] = now
            _CACHE["detail"] = f"holding last live LTP ({e})"
            return (
                float(_CACHE["ltp"]),
                str(_CACHE["detail"]),
                True,
                (_CACHE["prev_ltp"] if _CACHE.get("prev_ltp") is not None else None),
                True,
            )
        _CACHE.update({"t": now, "detail": str(e), "ok": False})
        return None, str(e), False, None, False

    ltp, detail, ok = _store_payload(payload, now=now)
    return ltp, detail, ok, (_CACHE["prev_ltp"] if _CACHE.get("prev_ltp") is not None else None), False


def get_dashboard_quote(*, force_refresh: bool = False) -> dict[str, Any]:
    """
    Quote for GET /angel/live-quote: prefer shared cache (engine may already refresh it).
    """
    if not force_refresh:
        cached = peek_shared_quote_payload(max_age_sec=1.25)
        if cached is not None:
            return cached

    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        raise RuntimeError("Angel One not configured: set ANGEL_API_KEY and ANGEL_JWT_TOKEN in backend/.env")

    payload = _fetch_live_payload()
    _store_payload(payload)
    # Always return the full payload (including disk fallback) for UI honesty.
    return payload


def clear_market_ltp_cache() -> None:
    _CACHE.update(
        {
            "t": 0.0,
            "live_t": 0.0,
            "ltp": None,
            "prev_ltp": None,
            "detail": None,
            "ok": False,
            "payload": None,
        }
    )
