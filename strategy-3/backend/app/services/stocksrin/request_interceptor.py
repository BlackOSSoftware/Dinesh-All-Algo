"""Pre-request: verify session and attach authenticated headers."""

from __future__ import annotations

import logging
from typing import Any

from app.services.stocksrin.header_provider import build_headers, log_header_attach
from app.services.stocksrin.session_manager import get_session_manager

LOG = logging.getLogger(__name__)


def prepare_get_request(
    path: str,
    params: dict[str, Any],
    *,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, str], Any]:
    """
    Verify session, return (headers, session).
    Raises StocksRinAuthError if session unavailable.
    """
    mgr = get_session_manager()
    session = mgr.ensure_session()
    log_header_attach(session)
    headers = build_headers(session, extra=extra_headers)
    LOG.info("Historical Request Sent: GET %s params=%s", path, list(params.keys()))
    return headers, session
