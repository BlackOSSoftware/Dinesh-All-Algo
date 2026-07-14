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

# Angel ~1 req/s; keep slightly above 1s. Sleep OUTSIDE the lock so other threads
# can still serve in-memory quote caches while one caller waits for a slot.
_MIN_INTERVAL_SEC = 1.05


def acquire_angel_upstream_slot() -> None:
    """Block until at least MIN_INTERVAL_SEC since the last Angel upstream request."""
    global _last_upstream_mono
    wait = 0.0
    with _lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _last_upstream_mono)
        if wait <= 0:
            _last_upstream_mono = now
            return
        # Reserve this slot now so concurrent waiters queue behind us.
        _last_upstream_mono = now + wait
    if wait > 0:
        time.sleep(wait)
