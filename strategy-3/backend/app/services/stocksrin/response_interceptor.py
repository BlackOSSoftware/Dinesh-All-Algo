"""Post-response: auth errors, cookie merge, retry signalling."""

from __future__ import annotations

import logging
from typing import Any

from app.services.stocksrin.cookie_store import merge_set_cookie_headers

LOG = logging.getLogger(__name__)

AUTH_HTTP_CODES = frozenset({401, 403})
SESSION_EXPIRED_MSG = (
    "StocksRin session expired. Historical data could not be loaded. Please login again."
)
AUTH_FAILED_MSG = (
    "StocksRin authentication failed. Session expired."
)


def is_auth_failure(status_code: int, body: Any) -> bool:
    if status_code in AUTH_HTTP_CODES:
        return True
    if isinstance(body, dict):
        msg = str(body.get("message") or body.get("error") or "").lower()
        if "invalid session" in msg or "not authorized" in msg or "unauthorized" in msg:
            return True
    return False


def apply_response_cookies(session: Any, response_headers: Any) -> None:
    merge_set_cookie_headers(session, response_headers)


def user_facing_auth_error(status_code: int | None = None) -> str:
    if status_code in AUTH_HTTP_CODES:
        return SESSION_EXPIRED_MSG
    return AUTH_FAILED_MSG


def log_response_status(path: str, status_code: int, *, retry: bool = False) -> None:
    suffix = " (retry)" if retry else ""
    LOG.info("Response Status: %s %d%s", path, status_code, suffix)
