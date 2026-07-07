"""
SENSEX index quote — LTP with close/disk fallback and Angel token recovery.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import BACKEND_ROOT, settings
from app.services.angel_quote import post_market_quote, _truthy_status

LOG = logging.getLogger(__name__)

_DISK_PATH = BACKEND_ROOT / "instance" / "sensex_last_ltp.json"
_LTP_KEYS = ("ltp", "Ltp", "lasttradedprice", "lastTradePrice", "lastPrice")
_CLOSE_KEYS = ("close", "Close", "prevClose", "previousClose", "PC", "open", "Open")

_last_login_mono: float = 0.0
_LOGIN_DEBOUNCE_SEC = 300.0


def _ist_now() -> datetime:
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except ZoneInfoNotFoundError:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _bse_session_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= minutes <= 15 * 60 + 30


def _is_token_error(msg: str) -> bool:
    t = (msg or "").lower()
    return (
        "invalid token" in t
        or "tokenexception" in t
        or "token is invalid" in t
        or ("jwt" in t and "expired" in t)
        or "access denied" in t
        or "ag8001" in t
        or "bad payload" in t
    )


def _pick_float(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            continue
    return None


def _price_from_row(row: dict[str, Any] | None) -> tuple[float | None, str]:
    if not row:
        return None, "LTP"
    ltp = _pick_float(row, _LTP_KEYS)
    close = _pick_float(row, _CLOSE_KEYS)
    if ltp is not None:
        return ltp, "LTP"
    if close is not None:
        return close, "CLOSE"
    return None, "LTP"


def _load_disk_ltp() -> float | None:
    if not _DISK_PATH.is_file():
        return None
    try:
        data = json.loads(_DISK_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            val = data.get("price") or data.get("ltp")
            if val is not None:
                p = float(val)
                return p if p > 0 else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _save_disk_ltp(price: float) -> None:
    if price <= 0:
        return
    _DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DISK_PATH.write_text(
        json.dumps({"price": price, "saved_at": time.time()}, indent=2),
        encoding="utf-8",
    )


def _maybe_restore_angel_session(*, reason: str) -> bool:
    global _last_login_mono

    from app.services.angel_jwt_refresh import try_refresh_angel_jwt_via_refresh_token

    if try_refresh_angel_jwt_via_refresh_token(reason=reason, force=True):
        return True

    now = time.monotonic()
    if now - _last_login_mono < _LOGIN_DEBOUNCE_SEC:
        return False
    _last_login_mono = now

    try:
        from app.services.angel_auto_login_scheduler import (
            apply_jwt_from_script_output,
            run_angel_smartapi_login_subprocess,
        )

        ok, stdout, _stderr, _rc = run_angel_smartapi_login_subprocess(reason=reason)
        if ok and apply_jwt_from_script_output(stdout):
            LOG.info("SENSEX quote: Angel session restored via login script (%s)", reason)
            return True
    except Exception as exc:  # noqa: BLE001
        LOG.warning("SENSEX quote: Angel login failed (%s): %s", reason, exc)
    return False


def _request_quote(
    *,
    mode: str,
    exchange_tokens: dict[str, list[str]],
) -> dict[str, Any]:
    return post_market_quote(
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


def _extract_rows(raw: dict[str, Any]) -> tuple[list[Any], list[Any], bool, str]:
    data = raw.get("data") if isinstance(raw, dict) else None
    fetched: list[Any] = []
    unfetched: list[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("fetched"), list):
            fetched = data["fetched"]
        if isinstance(data.get("unfetched"), list):
            unfetched = data["unfetched"]
    ok = _truthy_status(raw)
    msg = str(raw.get("message") or raw.get("Message") or "") if isinstance(raw, dict) else ""
    return fetched, unfetched, ok, msg


def _synthetic_row(price: float, *, price_type: str, source: str) -> dict[str, Any]:
    exchange, tokens = next(iter(settings_parsed_tokens().items()), ("BSE", ["99919000"]))
    return {
        "tradingSymbol": "SENSEX",
        "symbolToken": tokens[0] if tokens else "99919000",
        "exchange": exchange,
        "ltp": price,
        "close": price if price_type == "CLOSE" else None,
        "price_type": price_type,
        "quote_source": source,
    }


def settings_parsed_tokens() -> dict[str, list[str]]:
    raw = (settings.angel_exchange_tokens or "").strip()
    if not raw:
        return {"BSE": ["99919000"]}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k).upper(): [str(t) for t in v] for k, v in data.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        pass
    return {"BSE": ["99919000"]}


def fetch_sensex_live_quote(*, exchange_tokens: dict[str, list[str]], mode: str) -> dict[str, Any]:
    """
    Fetch SENSEX quote with LTP → OHLC close → disk last-price fallbacks.
    Attempts Angel token recovery once on invalid token.
    """
    from app.services.angel_jwt_refresh import reload_angel_tokens_from_env

    reload_angel_tokens_from_env()

    primary_mode = mode if mode in ("LTP", "OHLC", "FULL") else "LTP"
    modes_to_try = [primary_mode]
    if primary_mode == "LTP":
        modes_to_try.append("OHLC")

    fetched: list[Any] = []
    unfetched: list[Any] = []
    ok = False
    msg = ""
    price: float | None = None
    price_type = "LTP"
    quote_source = "live"

    for attempt in range(2):
        for quote_mode in modes_to_try:
            try:
                raw = _request_quote(mode=quote_mode, exchange_tokens=exchange_tokens)
            except RuntimeError as e:
                err = str(e)
                if _is_token_error(err) and attempt == 0 and _maybe_restore_angel_session(reason="sensex_quote"):
                    break
                msg = err
                ok = False
                continue
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                ok = False
                continue

            fetched, unfetched, ok, msg = _extract_rows(raw)
            row = fetched[0] if fetched and isinstance(fetched[0], dict) else None
            price, price_type = _price_from_row(row)
            if price is not None:
                quote_source = "live"
                break
        if price is not None:
            break
        if attempt == 0 and _is_token_error(msg) and _maybe_restore_angel_session(reason="sensex_quote_msg"):
            continue
        break

    session_open = _bse_session_open()
    if price is not None:
        _save_disk_ltp(price)
        if not session_open and price_type == "LTP":
            price_type = "LAST"
    else:
        disk = _load_disk_ltp()
        if disk is not None:
            price = disk
            price_type = "LAST"
            quote_source = "disk"
            fetched = [_synthetic_row(price, price_type=price_type, source=quote_source)]
            ok = True
            if _is_token_error(msg):
                msg = f"{msg} — showing last saved price"
            elif not msg:
                msg = "Showing last saved price (market closed or quote unavailable)"

    if price is not None and fetched and isinstance(fetched[0], dict):
        fetched[0] = {**fetched[0], "price_type": price_type, "quote_source": quote_source}

    live_quote = price is not None and quote_source == "live" and ok
    angel_ok = live_quote
    if price is None and not msg:
        msg = "No SENSEX price in Angel response"

    return {
        "angel_ok": angel_ok,
        "angel_message": msg,
        "mode": primary_mode,
        "fetched": fetched,
        "unfetched": unfetched,
        "as_of": time.time(),
        "market_open": session_open and price_type == "LTP" and quote_source == "live",
        "price_type": price_type,
        "quote_source": quote_source,
        "token_expired": _is_token_error(msg),
    }
