"""
Angel One SmartAPI — Live Market Quote (POST market/v1/quote/).

Docs: https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/
Uses headers as per official samples (X-PrivateKey, Bearer jwt, client IP/MAC, etc.).
"""

from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

LOG = logging.getLogger(__name__)

QUOTE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/"


def _truthy_status(payload: dict[str, Any]) -> bool:
    """Angel responses use `status` (bool) or sometimes `success` (bool)."""
    if "status" in payload:
        return bool(payload.get("status"))
    if "success" in payload:
        return bool(payload.get("success"))
    return False


def _angel_403_is_token(body_text: str, parsed: dict[str, Any] | None) -> bool:
    t = (body_text or "").lower()
    if "tokenexception" in t or "invalid token" in t or "token is invalid" in t:
        return True
    if isinstance(parsed, dict):
        et = str(parsed.get("error_type") or "").lower()
        if "token" in et:
            return True
    return False


def _angel_403_is_rate(body_text: str) -> bool:
    t = (body_text or "").lower()
    return "exceeding access rate" in t or "access rate" in t or "too many request" in t


def post_market_quote(
    *,
    api_key: str,
    jwt_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    mode: str,
    exchange_tokens: dict[str, list[str]],
    timeout_sec: float = 15.0,
    _retry_depth: int = 0,
) -> dict[str, Any]:
    """
    POST JSON body { mode, exchangeTokens } to Angel quote endpoint.
    Returns parsed JSON dict (raises on non-JSON or HTTP error after logging body).

    Uses a process-wide upstream gate + one retry on 403 (token refresh or rate backoff).
    """
    from app.config import settings
    from app.services.angel_upstream_gate import acquire_angel_upstream_slot

    acquire_angel_upstream_slot()

    body = {"mode": mode.upper(), "exchangeTokens": exchange_tokens}
    raw = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-PrivateKey": api_key,
        "X-SourceID": source_id,
        "X-ClientLocalIP": client_local_ip,
        "X-ClientPublicIP": client_public_ip,
        "X-MACAddress": mac_address,
        "X-UserType": user_type,
        "Authorization": f"Bearer {jwt_token}",
    }
    req = urllib.request.Request(QUOTE_URL, data=raw, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return json.loads(text)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except OSError:
            err_body = ""
        LOG.warning("Angel quote HTTP %s: %s", e.code, err_body[:2000])
        parsed: dict[str, Any] | None = None
        try:
            p = json.loads(err_body)
            if isinstance(p, dict):
                parsed = p
        except json.JSONDecodeError:
            pass

        if e.code == 403 and _retry_depth < 1:
            if _angel_403_is_token(err_body, parsed):
                from app.services.angel_jwt_refresh import try_refresh_angel_jwt_via_refresh_token

                if try_refresh_angel_jwt_via_refresh_token(reason="quote_403_token"):
                    jwt2 = (settings.angel_jwt_token or "").strip()
                    return post_market_quote(
                        api_key=api_key,
                        jwt_token=jwt2,
                        source_id=source_id,
                        client_local_ip=client_local_ip,
                        client_public_ip=client_public_ip,
                        mac_address=mac_address,
                        user_type=user_type,
                        mode=mode,
                        exchange_tokens=exchange_tokens,
                        timeout_sec=timeout_sec,
                        _retry_depth=_retry_depth + 1,
                    )
            if _angel_403_is_rate(err_body):
                time.sleep(2.6)
                return post_market_quote(
                    api_key=api_key,
                    jwt_token=jwt_token,
                    source_id=source_id,
                    client_local_ip=client_local_ip,
                    client_public_ip=client_public_ip,
                    mac_address=mac_address,
                    user_type=user_type,
                    mode=mode,
                    exchange_tokens=exchange_tokens,
                    timeout_sec=timeout_sec,
                    _retry_depth=_retry_depth + 1,
                )

        raise RuntimeError(f"Angel HTTP {e.code}: {err_body[:500]}") from e
    except urllib.error.URLError as e:
        LOG.warning("Angel quote network error: %s", e)
        raise RuntimeError(str(e.reason or e)) from e
