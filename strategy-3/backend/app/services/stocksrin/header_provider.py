"""Dynamic StocksRin request headers from active session."""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.stocksrin.cookie_store import StocksRinSession, cookies_header
from app.services.stocksrin.token_generator import generate_daily_app_authorization, generate_request_credentials

LOG = logging.getLogger(__name__)

_ORIGIN = "https://stocksrin.com"
_REFERER = "https://stocksrin.com/"


def normalize_authorization(raw: str) -> str:
    """StocksRin historical API expects raw app token — never Bearer prefix."""
    s = (raw or "").strip()
    if s.lower().startswith("bearer "):
        s = s[7:].strip()
    return s


def app_authorization(session: StocksRinSession | None = None) -> str:
    """Daily HMAC app token (StocksRin el()). Legacy .env token kept only as fallback."""
    daily = generate_daily_app_authorization()
    if daily:
        return daily
    if session and session.authorization.strip():
        return normalize_authorization(session.authorization)
    raw = (settings.stocksrin_app_authorization or settings.stocksrin_authorization or "").strip()
    return normalize_authorization(raw)


def build_headers(session: StocksRinSession, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    auth = app_authorization(session)
    nonce, request_token = generate_request_credentials(
        hmac_key=(settings.stocksrin_hmac_key or "stocksrinkey").strip()
    )
    headers: dict[str, str] = {
        "Authorization": auth,
        "x-request-token": request_token,
        "x-request-nonce": nonce,
        "x-user": session.user.strip(),
        "Accept": "application/json",
        "Origin": _ORIGIN,
        "Referer": _REFERER,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    cookie = cookies_header(session)
    if cookie:
        headers["Cookie"] = cookie
    if extra:
        headers.update(extra)
    LOG.debug(
        "Authorization Attached | Request Token Attached | Nonce Attached | user=%s",
        session.user,
    )
    return headers


def log_header_attach(session: StocksRinSession) -> None:
    LOG.info(
        "Authorization Attached | Request Token Attached | Nonce Attached | user=%s | cookies=%d",
        session.user,
        len(session.cookies),
    )


def session_from_response_headers(session: StocksRinSession, body: dict[str, Any] | None) -> bool:
    if not isinstance(body, dict):
        return False
    updated = False
    for src, dst in (
        ("authorization", "authorization"),
        ("Authorization", "authorization"),
        ("user", "user"),
        ("x-user", "user"),
        ("token", "jwt_token"),
    ):
        val = body.get(src)
        if val and str(val).strip():
            setattr(session, dst, str(val).strip())
            updated = True
    return updated
