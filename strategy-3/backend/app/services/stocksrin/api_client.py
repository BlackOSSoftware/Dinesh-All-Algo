"""Authenticated HTTP client for StocksRin historical API."""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.services.stocksrin.request_interceptor import prepare_get_request
from app.services.stocksrin.response_interceptor import (
    AUTH_FAILED_MSG,
    apply_response_cookies,
    is_auth_failure,
    log_response_status,
    user_facing_auth_error,
)
from app.services.stocksrin.session_manager import StocksRinAuthError, get_session_manager

LOG = logging.getLogger(__name__)


class StocksRinApiClient:
    def get(self, path: str, params: dict[str, Any]) -> tuple[int, Any, dict[str, Any]]:
        """
        GET with session headers. On 401/403: refresh session and retry once.
        Returns (status_code, parsed_body, request_meta).
        """
        mgr = get_session_manager()
        meta: dict[str, Any] = {"path": path, "params": dict(params), "retried": False}

        for attempt in range(2):
            headers, session = prepare_get_request(path, params)
            status, body, resp_headers = self._execute(path, params, headers)
            apply_response_cookies(session, resp_headers)
            log_response_status(path, status, retry=attempt > 0)

            if is_auth_failure(status, body):
                mgr.record_request(success=False, status_code=status, error=str(body))
                if attempt == 0:
                    LOG.warning("Response Status: %d — refresh session and retry", status)
                    LOG.info("Retry Request: GET %s", path)
                    if mgr.refresh():
                        meta["retried"] = True
                        continue
                raise StocksRinAuthError(user_facing_auth_error(status))

            mgr.record_request(success=status < 400, status_code=status)
            if status >= 400:
                err = body.get("error") if isinstance(body, dict) else str(body)
                raise RuntimeError(f"StocksRin API error {status}: {err}")
            return status, body, meta

        raise StocksRinAuthError(AUTH_FAILED_MSG)

    def _execute(
        self,
        path: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, Any, Any]:
        base = (settings.stocksrin_base_url or "https://apih.stocksrin.com").rstrip("/")
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{base}{path}?{qs}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        timeout = float(settings.stocksrin_request_timeout_sec or 30.0)
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    body = {"error": raw}
                return resp.status, body, resp.headers
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"error": raw or str(exc)}
            return exc.code, body, exc.headers


_client: StocksRinApiClient | None = None


def get_api_client() -> StocksRinApiClient:
    global _client
    if _client is None:
        _client = StocksRinApiClient()
    return _client
