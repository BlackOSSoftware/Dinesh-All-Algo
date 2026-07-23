"""
Serialize Angel SmartAPI HTTP across ALL strategy backends that share one account.

Angel enforces ~1 req/s per API key. This gate coordinates strategy-1..4 via
repo `.angel_shared/` so dashboards never hang waiting on long sleeps.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

_lock = threading.Lock()

# Angel ~1 req/s across all processes.
_MIN_INTERVAL_SEC = 1.10
_LOCK_STALE_SEC = 6.0
_LOCK_WAIT_SEC = 1.5
_BACKOFF_BASE_SEC = 2.0
_BACKOFF_MAX_SEC = 20.0
# FastAPI workers must not block longer than this — serve cache instead.
_MAX_ACQUIRE_WAIT_SEC = 0.85


class AngelUpstreamBusy(RuntimeError):
    """Shared Angel slot not available soon enough; callers should use cache."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def shared_angel_dir() -> Path:
    d = _repo_root() / ".angel_shared"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path() -> Path:
    return shared_angel_dir() / "angel_upstream_state.json"


def _lock_path() -> Path:
    return shared_angel_dir() / "angel_upstream.lock"


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _write_state(data: dict[str, Any]) -> None:
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        LOG.warning("Angel upstream state write failed: %s", exc)
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


def _acquire_file_lock() -> int | None:
    path = _lock_path()
    deadline = time.time() + _LOCK_WAIT_SEC
    while time.time() < deadline:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                os.write(fd, f"{os.getpid()}:{time.time():.3f}".encode("utf-8"))
            except OSError:
                pass
            return fd
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
                if age > _LOCK_STALE_SEC:
                    LOG.warning("Angel upstream lock stale (%.0fs) — removing", age)
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(0.02)
        except OSError as exc:
            LOG.warning("Angel upstream lock open failed: %s", exc)
            time.sleep(0.04)
    return None


def _release_file_lock(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        _lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def note_angel_rate_limit(*, detail: str = "") -> float:
    with _lock:
        fd = _acquire_file_lock()
        try:
            if fd is None:
                return _BACKOFF_BASE_SEC
            state = _read_state()
            streak = int(state.get("rate_limit_streak") or 0) + 1
            wait = min(_BACKOFF_MAX_SEC, _BACKOFF_BASE_SEC * (2 ** max(0, streak - 1)))
            state["rate_limit_streak"] = streak
            state["rate_limit_until"] = time.time() + wait
            state["rate_limit_detail"] = (detail or "")[:240]
            state["rate_limit_last_wall"] = time.time()
            _write_state(state)
            LOG.warning(
                "Angel RATE_LIMIT streak=%s backoff=%.1fs detail=%s",
                streak,
                wait,
                (detail or "")[:160],
            )
            return wait
        finally:
            _release_file_lock(fd)


def clear_angel_rate_limit() -> None:
    with _lock:
        fd = _acquire_file_lock()
        try:
            if fd is None:
                return
            state = _read_state()
            if not state.get("rate_limit_streak") and not state.get("rate_limit_until"):
                return
            state["rate_limit_streak"] = 0
            state["rate_limit_until"] = 0.0
            state.pop("rate_limit_detail", None)
            _write_state(state)
            LOG.info("Angel RATE_LIMIT cleared after successful upstream call")
        finally:
            _release_file_lock(fd)


def angel_rate_limit_remaining() -> float:
    state = _read_state()
    until = float(state.get("rate_limit_until") or 0.0)
    return max(0.0, until - time.time())


def note_angel_jwt_validated() -> None:
    with _lock:
        fd = _acquire_file_lock()
        try:
            if fd is None:
                return
            state = _read_state()
            state["last_jwt_validate_wall"] = time.time()
            _write_state(state)
            LOG.info("Angel JWT validate OK (shared stamp updated)")
        finally:
            _release_file_lock(fd)


def recent_angel_jwt_validated(*, max_age_sec: float = 480.0) -> bool:
    state = _read_state()
    last = float(state.get("last_jwt_validate_wall") or 0.0)
    if last <= 0:
        return False
    return (time.time() - last) < max_age_sec


def note_angel_jwt_refreshed(*, reason: str = "") -> None:
    with _lock:
        fd = _acquire_file_lock()
        try:
            if fd is None:
                return
            state = _read_state()
            state["last_jwt_refresh_wall"] = time.time()
            state["last_jwt_refresh_reason"] = (reason or "")[:120]
            _write_state(state)
            LOG.info("Angel JWT refresh noted (%s)", reason or "-")
        finally:
            _release_file_lock(fd)


def recent_angel_jwt_refresh(*, max_age_sec: float = 90.0) -> bool:
    state = _read_state()
    last = float(state.get("last_jwt_refresh_wall") or 0.0)
    if last <= 0:
        return False
    return (time.time() - last) < max_age_sec


def acquire_angel_upstream_slot(*, allow_wait_sec: float | None = None) -> None:
    """
    Claim the next Angel HTTP slot (fail-fast).

    Never sleeps inside the thread lock. If the slot is not free within
    allow_wait_sec, raises AngelUpstreamBusy so callers can serve cache.
    """
    max_wait = _MAX_ACQUIRE_WAIT_SEC if allow_wait_sec is None else max(0.0, float(allow_wait_sec))

    remaining = angel_rate_limit_remaining()
    if remaining > max_wait:
        raise AngelUpstreamBusy(f"Angel access rate cooldown ({remaining:.1f}s remaining)")
    if remaining > 0:
        time.sleep(remaining)

    wait = 0.0
    with _lock:
        fd = _acquire_file_lock()
        try:
            if fd is None:
                raise AngelUpstreamBusy("Angel upstream lock busy")
            state = _read_state()
            now = time.time()
            until = float(state.get("rate_limit_until") or 0.0)
            if until > now:
                rem = until - now
                if rem > max_wait:
                    raise AngelUpstreamBusy(f"Angel access rate cooldown ({rem:.1f}s remaining)")
                wait = rem
            else:
                last = float(state.get("last_upstream_wall") or 0.0)
                wait = max(0.0, _MIN_INTERVAL_SEC - (now - last))
                if wait > max_wait:
                    raise AngelUpstreamBusy(f"Angel upstream slot wait {wait:.2f}s (use cache)")
                state["last_upstream_wall"] = now + wait
                state["last_upstream_pid"] = os.getpid()
                _write_state(state)
        finally:
            _release_file_lock(fd)

    # Sleep OUTSIDE thread lock so sibling workers can serve memory/shared cache.
    if wait > 0:
        LOG.debug("Angel upstream slot wait=%.2fs pid=%s", wait, os.getpid())
        time.sleep(wait)
        fd2 = _acquire_file_lock()
        try:
            if fd2 is None:
                return
            state = _read_state()
            state["last_upstream_wall"] = time.time()
            state["last_upstream_pid"] = os.getpid()
            _write_state(state)
        finally:
            _release_file_lock(fd2)
