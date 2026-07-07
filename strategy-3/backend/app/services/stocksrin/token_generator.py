"""StocksRin request nonce + HMAC token (matches browser rB() in StocksRin SPA)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

_DAILY_AUTH_SALT = "srsecretsalt"
_daily_auth_cache: tuple[str, str] | None = None


def generate_daily_app_authorization(*, utc_date: str | None = None) -> str:
    """
    StocksRin SPA el(): Authorization = HMAC-SHA256(UTC date YYYY-MM-DD, srsecretsalt).
    Regenerated once per UTC day (cached in-process).
    """
    global _daily_auth_cache
    date = utc_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _daily_auth_cache and _daily_auth_cache[0] == date:
        return _daily_auth_cache[1]
    token = hmac.new(_DAILY_AUTH_SALT.encode("utf-8"), date.encode("utf-8"), hashlib.sha256).hexdigest()
    _daily_auth_cache = (date, token)
    return token


def generate_request_credentials(*, hmac_key: str = "stocksrinkey") -> tuple[str, str]:
    """
    Returns (nonce, request_token).
    nonce: 32 hex chars (16 random bytes)
    token: HMAC-SHA256(nonce, hmac_key) as hex
    """
    nonce = secrets.token_hex(16)
    token = hmac.new(hmac_key.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    return nonce, token
