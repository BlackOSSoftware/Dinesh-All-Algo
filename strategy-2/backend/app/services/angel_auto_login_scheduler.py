"""
Angel One SmartAPI — daily auto-login via scripts/angel_smartapi_login.py.

- Runs at 00:30 server time (APScheduler cron) for full TOTP login.
- Every 8h: renews JWT via ANGEL_REFRESH_TOKEN when set (no TOTP).
- On success: updates ANGEL_JWT_TOKEN (+ optional ANGEL_REFRESH_TOKEN) in .env, runtime, clears caches.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

SCHED_PREFIX = "[Scheduler]"
JOB_DAILY_ID = "angel_smartapi_daily_login"
JOB_RETRY_ID = "angel_smartapi_login_retry_once"
JOB_REFRESH_ID = "angel_jwt_refresh_interval"

_scheduler: Any = None


def backend_root() -> Path:
    """backend/ directory (parent of app/)."""
    # This file: backend/app/services/angel_auto_login_scheduler.py
    return Path(__file__).resolve().parent.parent.parent


def venv_python_path(root: Path | None = None) -> Path:
    r = root or backend_root()
    if sys.platform == "win32":
        return r / ".venv" / "Scripts" / "python.exe"
    return r / ".venv" / "bin" / "python"


def login_script_path(root: Path | None = None) -> Path:
    return (root or backend_root()) / "scripts" / "angel_smartapi_login.py"


def verify_angel_login_paths() -> tuple[bool, list[str]]:
    """Return (ok, error_messages)."""
    root = backend_root()
    errs: list[str] = []
    script = login_script_path(root)
    if not script.is_file():
        errs.append(f"Angel login script not found (expected): {script}")
    return (len(errs) == 0, errs)


def login_python_command(root: Path | None = None) -> list[str]:
    """Prefer backend venv; fallback to the current Python executable."""
    r = root or backend_root()
    py = venv_python_path(r)
    if py.is_file():
        return [str(py)]
    if sys.executable:
        return [sys.executable]
    return ["python"]


def _mask_jwt_in_log(text: str) -> str:
    return re.sub(
        r"(ANGEL_JWT_TOKEN=)([^\s\r\n#]+)",
        r"\1***redacted***",
        text,
        flags=re.IGNORECASE,
    )


def _parse_jwt_from_stdout(stdout: str) -> str | None:
    for line in stdout.splitlines():
        s = line.strip()
        if s.upper().startswith("ANGEL_JWT_TOKEN="):
            val = s.split("=", 1)[1].strip().strip('"').strip("'")
            if val and not val.startswith("#"):
                return val
    return None


def _update_env_file_jwt(env_path: Path, new_jwt: str) -> None:
    """Insert or replace ANGEL_JWT_TOKEN in backend/.env (no other lines changed)."""
    token_line = f"ANGEL_JWT_TOKEN={new_jwt}"
    if not env_path.is_file():
        env_path.write_text(token_line + "\n", encoding="utf-8")
        return
    raw = env_path.read_text(encoding="utf-8")
    pat = re.compile(r"(?m)^ANGEL_JWT_TOKEN\s*=.*$")
    if pat.search(raw):
        new_raw = pat.sub(token_line, raw)
    else:
        base = raw.rstrip()
        new_raw = (base + "\n" if base else "") + token_line + "\n"
    env_path.write_text(new_raw, encoding="utf-8")


def _apply_jwt_runtime(new_jwt: str) -> None:
    """Update os.environ and global settings so quote routes pick up new token without restart."""
    from app.config import settings

    tok = new_jwt.strip()
    os.environ["ANGEL_JWT_TOKEN"] = tok
    object.__setattr__(settings, "angel_jwt_token", tok)


def _clear_quote_caches() -> None:
    from app.routers import angel as angel_router

    angel_router.clear_angel_caches()


def run_angel_smartapi_login_subprocess(*, reason: str) -> tuple[bool, str, str, int]:
    """
    Run angel_smartapi_login.py with venv Python. Returns (success, stdout, stderr, returncode).
    Never raises — errors are captured in stderr / returncode.
    """
    root = backend_root()
    script = login_script_path(root)
    if not script.is_file():
        msg = f"missing login script (script={script})"
        LOG.error("%s Running Angel One login refresh aborted: %s", SCHED_PREFIX, msg)
        return False, "", msg, 127
    py_cmd = login_python_command(root)

    LOG.info("%s Running Angel One login refresh... (%s)", SCHED_PREFIX, reason)
    try:
        proc = subprocess.run(
            [*py_cmd, str(script)],
            cwd=str(root / "scripts"),
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ},
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        LOG.debug("%s angel_smartapi_login.py stdout:\n%s", SCHED_PREFIX, _mask_jwt_in_log(out) or "(empty)")
        LOG.debug("%s angel_smartapi_login.py stderr:\n%s", SCHED_PREFIX, _mask_jwt_in_log(err) or "(empty)")
        ok = proc.returncode == 0
        if ok:
            LOG.info("%s angel_smartapi_login.py completed (exit 0)", SCHED_PREFIX)
        else:
            LOG.error("%s Login refresh failed: exit_code=%s", SCHED_PREFIX, proc.returncode)
        return ok, out, err, proc.returncode
    except subprocess.TimeoutExpired as e:
        LOG.error("%s Login refresh failed: timeout after 120s", SCHED_PREFIX)
        return False, "", str(e), -1
    except Exception as e:  # noqa: BLE001
        LOG.exception("%s Login refresh failed: %s", SCHED_PREFIX, e)
        return False, "", str(e), -1


def apply_jwt_from_script_output(stdout: str) -> bool:
    """Parse JWT (and optional refresh token) from script stdout, write .env, update runtime, clear caches."""
    from app.services.angel_jwt_refresh import parse_angel_refresh_from_login_stdout, save_refresh_token_to_env_and_runtime

    jwt = _parse_jwt_from_stdout(stdout)
    if not jwt:
        LOG.error("%s Login refresh failed: could not parse ANGEL_JWT_TOKEN from script stdout", SCHED_PREFIX)
        return False
    env_path = backend_root() / ".env"
    try:
        _update_env_file_jwt(env_path, jwt)
        _apply_jwt_runtime(jwt)
        rt = parse_angel_refresh_from_login_stdout(stdout)
        if rt:
            save_refresh_token_to_env_and_runtime(rt)
        _clear_quote_caches()
        LOG.info("%s Login refresh successful", SCHED_PREFIX)
        LOG.info("%s ANGEL_JWT_TOKEN written to .env; in-memory JWT length=%d", SCHED_PREFIX, len(jwt))
        return True
    except OSError as e:
        LOG.error("%s Login refresh failed: could not write .env: %s", SCHED_PREFIX, e)
        return False


def _sync_login_job(reason: str, allow_retry: bool) -> None:
    ok, stdout, _stderr, _rc = run_angel_smartapi_login_subprocess(reason=reason)
    if not ok:
        if allow_retry:
            LOG.info("%s Scheduling single retry in 5 minutes...", SCHED_PREFIX)
            schedule_retry_once()
        return
    if not apply_jwt_from_script_output(stdout):
        if allow_retry:
            LOG.info("%s Scheduling single retry in 5 minutes (apply failed)...", SCHED_PREFIX)
            schedule_retry_once()


def schedule_retry_once() -> None:
    global _scheduler
    if _scheduler is None:
        LOG.warning("%s Cannot schedule retry: scheduler not running.", SCHED_PREFIX)
        return
    run_at = datetime.now() + timedelta(minutes=5)

    async def _retry_async() -> None:
        await _async_login_job("retry_after_failure", False)

    _scheduler.add_job(
        _retry_async,
        "date",
        run_date=run_at,
        id=JOB_RETRY_ID,
        replace_existing=True,
    )
    LOG.info("%s Retry job registered at %s", SCHED_PREFIX, run_at.isoformat(timespec="seconds"))


async def _async_login_job(reason: str, allow_retry: bool) -> None:
    await asyncio.to_thread(_sync_login_job, reason, allow_retry)


async def _async_refresh_token_job() -> None:
    await asyncio.to_thread(_sync_refresh_token_job)


def _sync_refresh_token_job() -> None:
    try:
        from app.services.angel_jwt_refresh import try_refresh_angel_jwt_via_refresh_token

        try_refresh_angel_jwt_via_refresh_token(reason="scheduler_interval")
    except Exception as e:  # noqa: BLE001
        LOG.warning("%s Scheduled JWT refresh error: %s", SCHED_PREFIX, e)


def start_angel_auto_login_scheduler() -> None:
    """Start APScheduler with daily 00:30 job. Safe to call once; replaces existing scheduler."""
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    ok, errs = verify_angel_login_paths()
    if not ok:
        for e in errs:
            LOG.error("%s %s", SCHED_PREFIX, e)
        LOG.error("%s Angel One auto-login is disabled until paths exist.", SCHED_PREFIX)
        return

    if _scheduler is not None:
        LOG.warning("%s Scheduler already running; skip duplicate start.", SCHED_PREFIX)
        return

    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )

    async def _daily_async() -> None:
        await _async_login_job("cron_00_30", True)

    _scheduler.add_job(
        _daily_async,
        CronTrigger(hour=0, minute=30),
        id=JOB_DAILY_ID,
        replace_existing=True,
    )
    _scheduler.add_job(
        _async_refresh_token_job,
        IntervalTrigger(hours=8),
        id=JOB_REFRESH_ID,
        replace_existing=True,
    )
    _scheduler.start()
    LOG.info("%s Angel One auto-login scheduled for 00:30 daily; JWT refresh via token every 8h", SCHED_PREFIX)


def stop_angel_auto_login_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception as e:  # noqa: BLE001
        LOG.warning("%s Scheduler shutdown: %s", SCHED_PREFIX, e)
    _scheduler = None
    LOG.info("%s Angel auto-login scheduler stopped", SCHED_PREFIX)


def trigger_manual_angel_login() -> dict[str, Any]:
    """
    Synchronous manual run (for API handler). Runs in thread pool if called from async.
    Tries lightweight refresh-token exchange first, then full TOTP login script.
    """
    from app.services.angel_jwt_refresh import try_refresh_angel_jwt_via_refresh_token

    if try_refresh_angel_jwt_via_refresh_token(reason="manual_api", force=True):
        return {"ok": True, "message": "Angel session refreshed (refresh token)"}

    ok, errs = verify_angel_login_paths()
    if not ok:
        return {"ok": False, "error": "; ".join(errs)}
    ok_run, stdout, stderr, rc = run_angel_smartapi_login_subprocess(reason="manual")
    if not ok_run:
        return {
            "ok": False,
            "error": f"script exit {rc}",
            "stderr_tail": (stderr or "")[-2000:],
        }
    if not apply_jwt_from_script_output(stdout):
        return {"ok": False, "error": "could not parse or apply ANGEL_JWT_TOKEN"}
    return {"ok": True, "message": "Angel session refreshed"}


async def trigger_manual_angel_login_async() -> dict[str, Any]:
    return await asyncio.to_thread(trigger_manual_angel_login)
