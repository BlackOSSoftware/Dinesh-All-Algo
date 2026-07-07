"""StocksRin mgmt login — obtains JWT and user id for historical API."""

from __future__ import annotations

import base64
import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

from app.config import settings
from app.services.stocksrin.token_generator import generate_daily_app_authorization

LOG = logging.getLogger(__name__)

_LOGIN_URL = "https://api.stocksrin.com/mgmt/auth/login"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        part = token.split(".")[1]
        pad = "=" * ((4 - len(part) % 4) % 4)
        raw = base64.urlsafe_b64decode(part + pad)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (IndexError, json.JSONDecodeError, ValueError):
        return {}


def user_id_from_jwt(jwt_token: str) -> str:
    payload = _decode_jwt_payload(jwt_token)
    claim = payload.get("claim") if isinstance(payload.get("claim"), dict) else {}
    return str(claim.get("userID") or claim.get("userId") or "").strip()


def login(
    *,
    email: str,
    password_b64: str,
    app_authorization: str | None = None,
    device_id: str | None = None,
    device_type: str | None = None,
) -> dict[str, Any]:
    """
    POST /mgmt/auth/login
    password_b64: base64-encoded password (as sent by StocksRin web app).
    Returns {token, user_id, claim}.
    """
    auth = (
        app_authorization
        or generate_daily_app_authorization()
        or settings.stocksrin_app_authorization
        or settings.stocksrin_authorization
        or ""
    ).strip()
    if not auth:
        raise ValueError("StocksRin app authorization unavailable")
    if not email.strip() or not password_b64.strip():
        raise ValueError("STOCKSRIN_EMAIL and STOCKSRIN_PASSWORD_B64 required for login")

    body = json.dumps({"email": email.strip(), "password": password_b64.strip()}).encode("utf-8")
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": auth,
        "x-device-id": (device_id or settings.stocksrin_device_id or "device_strategy3").strip(),
        "x-device-type": (device_type or settings.stocksrin_device_type or "laptop").strip(),
        "Origin": "https://stocksrin.com",
        "Referer": "https://stocksrin.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    req = urllib.request.Request(_LOGIN_URL, data=body, headers=headers, method="POST")
    timeout = float(settings.stocksrin_request_timeout_sec or 30.0)
    ctx = ssl.create_default_context()
    LOG.info("Authentication Started: StocksRin login for %s", email.strip())
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"StocksRin login failed HTTP {exc.code}: {raw[:200]}") from exc

    jwt = str(data.get("token") or "").strip()
    if not jwt:
        raise RuntimeError("StocksRin login returned no token")
    user_id = user_id_from_jwt(jwt)
    if not user_id:
        raise RuntimeError("StocksRin login JWT missing userID claim")
    claim = _decode_jwt_payload(jwt).get("claim", {})
    LOG.info("Session Loaded: login OK user=%s", user_id)
    return {"token": jwt, "user_id": user_id, "claim": claim}
