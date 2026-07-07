"""StocksRin session lifecycle: load, login, validate, refresh, cache."""

from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.services.stocksrin.cookie_store import (
    StocksRinSession,
    import_session_payload,
    load_session,
    merge_set_cookie_headers,
    save_session,
    session_file_path,
)
from app.services.stocksrin.header_provider import app_authorization, build_headers, session_from_response_headers
from app.services.stocksrin.login_client import login, user_id_from_jwt

LOG = logging.getLogger(__name__)

SESSION_EXPIRED_MSG = (
    "StocksRin session expired. Historical data could not be loaded. Please login again."
)

_PROBE_PATH = "/history/data/historical/spot/chart"


class StocksRinAuthError(RuntimeError):
    """Raised when StocksRin session cannot authenticate."""


@dataclass
class AuthStats:
    session_active: bool = False
    current_user: str = ""
    last_refresh_time: float | None = None
    historical_requests: int = 0
    successful_requests: int = 0
    auth_401_count: int = 0
    last_api_status: str = ""
    last_error: str = ""

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "authenticationStatus": "active" if self.session_active else "inactive",
            "sessionActive": self.session_active,
            "lastRefreshTime": self.last_refresh_time,
            "currentUser": self.current_user,
            "apiStatus": self.last_api_status,
            "historicalRequests": self.historical_requests,
            "successfulRequests": self.successful_requests,
            "401Count": self.auth_401_count,
            "lastError": self.last_error,
        }


class SessionManager:
    def __init__(self) -> None:
        self._session: StocksRinSession | None = None
        self._stats = AuthStats()
        self._validated_at: float = 0.0
        self._validate_ttl_sec = 120.0

    @property
    def stats(self) -> AuthStats:
        return self._stats

    @property
    def session(self) -> StocksRinSession | None:
        return self._session

    def is_configured(self) -> bool:
        if self._session and self._session.is_complete():
            return True
        return self._can_login()

    def _can_login(self) -> bool:
        return bool(
            (settings.stocksrin_email or "").strip()
            and (settings.stocksrin_password_b64 or "").strip()
        )

    def load(self) -> bool:
        LOG.info("Authentication Started")
        sess = load_session()
        if sess and sess.is_complete():
            self._apply_session(sess)
            LOG.info("Session Loaded: user=%s (file)", sess.user)
            return True
        if self._login_and_save():
            return True
        if self._migrate_from_env():
            LOG.info("Session Loaded: migrated from legacy .env")
            return True
        self._session = None
        self._stats.session_active = False
        LOG.warning(
            "Session Loaded: no session — set STOCKSRIN_EMAIL + STOCKSRIN_PASSWORD_B64 + "
            "STOCKSRIN_APP_AUTHORIZATION in .env or run scripts/import_stocksrin_session.py"
        )
        return False

    def _apply_session(self, sess: StocksRinSession) -> None:
        if not sess.authorization.strip():
            sess.authorization = app_authorization(sess)
        self._session = sess
        self._stats.session_active = True
        self._stats.current_user = sess.user
        self._stats.last_refresh_time = sess.last_refresh_at or sess.imported_at or time.time()

    def _login_and_save(self) -> bool:
        if not self._can_login():
            return False
        try:
            result = login(
                email=settings.stocksrin_email.strip(),
                password_b64=settings.stocksrin_password_b64.strip(),
            )
        except (RuntimeError, ValueError) as exc:
            LOG.warning("StocksRin login failed: %s", exc)
            self._stats.last_error = str(exc)
            return False
        sess = StocksRinSession(
            authorization=app_authorization(None),
            user=result["user_id"],
            jwt_token=result["token"],
            source="login",
        )
        save_session(sess)
        self._apply_session(sess)
        LOG.info("Session Refreshed: login OK user=%s", sess.user)
        return True

    def _migrate_from_env(self) -> bool:
        auth = app_authorization(None)
        user = (settings.stocksrin_user or "").strip()
        if not auth or not user:
            return False
        try:
            sess = import_session_payload(
                {"authorization": auth, "user": user, "cookies": {}},
                source="env_migration",
            )
            self._apply_session(sess)
            return True
        except ValueError:
            return False

    def ensure_session(self) -> StocksRinSession:
        if self._session is None or not self._session.is_complete():
            if not self.load():
                raise StocksRinAuthError(
                    "StocksRin not configured. Set STOCKSRIN_EMAIL, STOCKSRIN_PASSWORD_B64, "
                    f"STOCKSRIN_APP_AUTHORIZATION in .env or import session to {session_file_path()}."
                )
        assert self._session is not None
        return self._session

    def validate(self, *, force: bool = False) -> bool:
        if not force and time.monotonic() - self._validated_at < self._validate_ttl_sec:
            return self._stats.session_active
        try:
            status, _ = self._probe()
            ok = status == 200
            self._stats.session_active = ok
            if ok:
                self._validated_at = time.monotonic()
            return ok
        except StocksRinAuthError:
            self._stats.session_active = False
            return False

    def refresh(self) -> bool:
        LOG.info("Session Refreshed: attempting login / reload")
        self._validated_at = 0.0
        if self._login_and_save() and self.validate(force=True):
            return True
        sess = load_session()
        if sess and sess.is_complete():
            self._apply_session(sess)
            if self.validate(force=True):
                LOG.info("Session Refreshed: reloaded file session user=%s", sess.user)
                return True
        LOG.warning("Session Refreshed: failed")
        self._stats.session_active = False
        return False

    def _probe(self) -> tuple[int, Any]:
        session = self.ensure_session()
        headers = build_headers(session)
        base = (settings.stocksrin_base_url or "https://apih.stocksrin.com").rstrip("/")
        params = {"symbol": "SENSEX", "from": 0, "to": 1, "resolution": 10, "exchange": "BSE"}
        url = f"{base}{_PROBE_PATH}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        timeout = float(settings.stocksrin_request_timeout_sec or 30.0)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                merge_set_cookie_headers(session, resp.headers)
                body_raw = resp.read().decode("utf-8", errors="replace")
                try:
                    body = json.loads(body_raw) if body_raw else {}
                except json.JSONDecodeError:
                    body = {}
                session_from_response_headers(session, body if isinstance(body, dict) else {})
                save_session(session)
                return resp.status, body
        except urllib.error.HTTPError as exc:
            body_raw = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(body_raw) if body_raw else {}
            except json.JSONDecodeError:
                body = {"error": body_raw}
            return exc.code, body

    def record_request(self, *, success: bool, status_code: int, error: str = "") -> None:
        self._stats.historical_requests += 1
        if success:
            self._stats.successful_requests += 1
            self._stats.last_api_status = "success"
        else:
            self._stats.last_error = error
            self._stats.last_api_status = str(status_code)
            if status_code in (401, 403):
                self._stats.auth_401_count += 1


_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
        _manager.load()
    return _manager


def reset_session_manager() -> None:
    global _manager
    _manager = None
