"""Persistent StocksRin session + cookie storage."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT, settings

LOG = logging.getLogger(__name__)

DEFAULT_SESSION_PATH = BACKEND_ROOT / "instance" / "stocksrin_session.json"


@dataclass
class StocksRinSession:
    authorization: str = ""
    user: str = ""
    jwt_token: str = ""
    request_token: str = ""
    request_nonce: str = ""
    cookies: dict[str, str] = field(default_factory=dict)
    imported_at: float = 0.0
    last_refresh_at: float = 0.0
    source: str = "unknown"

    def is_complete(self) -> bool:
        from app.services.stocksrin.header_provider import app_authorization

        return bool(app_authorization(self) and self.user.strip())


def session_file_path() -> Path:
    raw = (getattr(settings, "stocksrin_session_file", None) or "").strip()
    return Path(raw) if raw else DEFAULT_SESSION_PATH


def load_session() -> StocksRinSession | None:
    path = session_file_path()
    if not path.is_file():
        LOG.debug("Cookie Loaded: no session file at %s", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("Cookie Loaded: failed to read %s — %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    cookies = data.get("cookies") or {}
    if not isinstance(cookies, dict):
        cookies = {}
    sess = StocksRinSession(
        authorization=_pick(data, "authorization", "Authorization", "STOCKSRIN_AUTHORIZATION")
        or (settings.stocksrin_app_authorization or settings.stocksrin_authorization or "").strip(),
        user=_pick(data, "user", "x-user", "x_user"),
        jwt_token=_pick(data, "jwt_token", "jwt", "token"),
        request_token=_pick(data, "request_token", "x-request-token", "requestToken"),
        request_nonce=_pick(data, "request_nonce", "x-request-nonce", "requestNonce"),
        cookies={str(k): str(v) for k, v in cookies.items()},
        imported_at=float(data.get("imported_at") or data.get("importedAt") or 0),
        last_refresh_at=float(data.get("last_refresh_at") or data.get("lastRefreshAt") or 0),
        source=str(data.get("source") or "file"),
    )
    if sess.is_complete():
        LOG.info("Cookie Loaded: session file %s (user=%s, cookies=%d)", path, sess.user, len(sess.cookies))
        return sess
    LOG.warning("Cookie Loaded: incomplete session in %s", path)
    return None


def save_session(session: StocksRinSession) -> None:
    path = session_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    if not session.imported_at:
        session.imported_at = now
    session.last_refresh_at = now
    payload = {
        "authorization": session.authorization,
        "user": session.user,
        "jwt_token": session.jwt_token,
        "cookies": session.cookies,
        "imported_at": session.imported_at,
        "last_refresh_at": session.last_refresh_at,
        "source": session.source,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOG.info("Session saved to %s (user=%s)", path, session.user)


def merge_set_cookie(session: StocksRinSession, set_cookie_header: str | None) -> None:
    if not set_cookie_header:
        return
    jar = SimpleCookie()
    jar.load(set_cookie_header)
    for key, morsel in jar.items():
        session.cookies[key] = morsel.value
        LOG.debug("Cookie updated: %s", key)


def merge_set_cookie_headers(session: StocksRinSession, headers: Any) -> None:
    if headers is None:
        return
    if hasattr(headers, "get_all"):
        for val in headers.get_all("Set-Cookie") or []:
            merge_set_cookie(session, val)
    else:
        raw = headers.get("Set-Cookie") if hasattr(headers, "get") else None
        if raw:
            merge_set_cookie(session, raw)


def cookies_header(session: StocksRinSession) -> str:
    return "; ".join(f"{k}={v}" for k, v in session.cookies.items() if k and v)


def import_session_payload(data: dict[str, Any], *, source: str = "import") -> StocksRinSession:
    cookies = data.get("cookies") or {}
    if not isinstance(cookies, dict):
        cookies = {}
    sess = StocksRinSession(
        authorization=_pick(data, "authorization", "Authorization")
        or (settings.stocksrin_app_authorization or settings.stocksrin_authorization or "").strip(),
        user=_pick(data, "user", "x-user"),
        jwt_token=_pick(data, "jwt_token", "jwt", "token"),
        request_token=_pick(data, "request_token", "x-request-token", "requestToken"),
        request_nonce=_pick(data, "request_nonce", "x-request-nonce", "requestNonce"),
        cookies={str(k): str(v) for k, v in cookies.items()},
        imported_at=time.time(),
        source=source,
    )
    if not sess.is_complete():
        raise ValueError(
            "Session import incomplete — need app authorization + user (or run login import)"
        )
    save_session(sess)
    return sess


def _pick(data: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = data.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""
