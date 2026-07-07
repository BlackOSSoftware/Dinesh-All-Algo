"""
Shared index LTP fetch for trading engine (throttled; respects Angel rate limits).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings
from app.services.angel_quote import post_market_quote, _truthy_status

LOG = logging.getLogger(__name__)

_CACHE: dict[str, Any] = {"t": 0.0, "ltp": None, "detail": None, "ok": False}


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


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            x = float(v)
            return x if x == x else None
        except ValueError:
            return None
    return None


def _pick_row(rows: list[Any]) -> dict[str, Any] | None:
    if not rows:
        return None
    for r in rows:
        if isinstance(r, dict):
            return r
    return None


def _ltp_from_row(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    for k in ("ltp", "Ltp", "lasttradedprice", "lastTradePrice", "close", "Close", "open", "Open"):
        n = _num(row.get(k))
        if n is not None and n > 0:
            return n
    return None


def get_index_ltp_cached(ttl_sec: float = 1.4) -> tuple[float | None, str | None, bool]:
    """
    Returns (ltp, detail_message, market_ok).
    """
    now = time.monotonic()
    if _CACHE["ltp"] is not None and now - float(_CACHE["t"]) < ttl_sec:
        return float(_CACHE["ltp"]), str(_CACHE["detail"] or ""), bool(_CACHE["ok"])

    if not (settings.angel_api_key or "").strip() or not (settings.angel_jwt_token or "").strip():
        _CACHE.update({"t": now, "ltp": None, "detail": "Angel not configured", "ok": False})
        return None, "Angel not configured", False

    exchange_tokens = _parse_exchange_tokens(settings.angel_exchange_tokens)
    if not exchange_tokens:
        _CACHE.update({"t": now, "ltp": None, "detail": "ANGEL_EXCHANGE_TOKENS empty", "ok": False})
        return None, "ANGEL_EXCHANGE_TOKENS empty", False

    mode = (settings.angel_quote_mode or "LTP").strip().upper()
    if mode not in ("LTP", "OHLC", "FULL"):
        mode = "LTP"

    try:
        raw = post_market_quote(
            api_key=settings.angel_api_key.strip(),
            jwt_token=settings.angel_jwt_token.strip(),
            source_id=(settings.angel_source_id or "WEB").strip(),
            client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
            client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
            mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
            user_type=(settings.angel_user_type or "USER").strip(),
            mode=mode,
            exchange_tokens=exchange_tokens,
        timeout_sec=min(float(settings.angel_request_timeout_sec or 5.0), 5.0),
        )
    except RuntimeError as e:
        LOG.warning("market_ltp quote failed: %s", e)
        _CACHE.update({"t": now, "ltp": None, "detail": str(e), "ok": False})
        return None, str(e), False

    ok = _truthy_status(raw) if isinstance(raw, dict) else False
    msg = ""
    if isinstance(raw, dict):
        msg = str(raw.get("message") or raw.get("Message") or "")
    fetched: list[Any] = []
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, dict) and isinstance(data.get("fetched"), list):
        fetched = data["fetched"]

    row = _pick_row(fetched)
    ltp = _ltp_from_row(row)
    detail = msg or ("" if ltp else "No LTP in quote response")
    _CACHE.update({"t": now, "ltp": ltp, "detail": detail, "ok": ok and ltp is not None})
    return ltp, detail, bool(ok and ltp is not None)


def clear_market_ltp_cache() -> None:
    _CACHE["t"] = 0.0
