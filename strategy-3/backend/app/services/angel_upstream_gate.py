"""
Serialize all Angel SmartAPI HTTP calls (quote, candles, token refresh) so we stay
under Angel's ~1 req/s style limits across endpoints. Multiple clients (dashboard
poll + trading engine) share one process-wide gate.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_last_upstream_mono: float = 0.0

# Angel returns 403 "exceeding access rate" if calls are too close; stay conservative.
_MIN_INTERVAL_SEC = 1.28


def acquire_angel_upstream_slot() -> None:
    """Block until at least MIN_INTERVAL_SEC since the last Angel upstream request."""
    global _last_upstream_mono
    with _lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _last_upstream_mono)
        if wait > 0:
            time.sleep(wait)
        _last_upstream_mono = time.monotonic()
