"""
Angel One SmartAPI — daily auto-login via scripts/angel_smartapi_login.py.

- Runs at 00:30 Asia/Kolkata (APScheduler cron) for full TOTP login.
- Runs at 08:59 Asia/Kolkata Mon–Fri for pre-market token generate / login.
- Every 20 min: JWT health check / renew via ANGEL_REFRESH_TOKEN when set (no TOTP).
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
JOB_PREMARKET_ID = "angel_smartapi_premarket_login"
JOB_RETRY_ID = "angel_smartapi_login_retry_once"
JOB_REFRESH_ID = "angel_jwt_refresh_interval"
IST = "Asia/Kolkata"

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


def _python_supports_angel_login(py: str) -> bool:
    """True when this interpreter can import SmartAPI login deps."""
    try:
        proc = subprocess.run(
            [
                py,
                "-c",
                "import SmartApi.smartConnect; import pyotp; from dotenv import load_dotenv",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def login_python_command(root: Path | None = None) -> list[str]:
    """
    Prefer a Python that actually has smartapi-python/pyotp.

    VPS note: an empty/broken backend/.venv often exists while uvicorn runs under
    another interpreter — always probing first avoids false "script exit 1".
    """
    r = root or backend_root()
    candidates: list[str] = []
    if sys.executable:
        candidates.append(sys.executable)
    vpy = venv_python_path(r)
    if vpy.is_file():
        candidates.append(str(vpy))
    candidates.extend(["python3", "python"])

    seen: set[str] = set()
    for cand in candidates:
        key = cand.lower()
        if key in seen:
            continue
        seen.add(key)
        if _python_supports_angel_login(cand):
            LOG.info("%s Using Angel login interpreter: %s", SCHED_PREFIX, cand)
            return [cand]

    # Last resort — previous behaviour (may still fail with a clear ImportError).
    if sys.executable:
        LOG.warning(
            "%s No interpreter passed SmartAPI import probe; falling back to %s",
            SCHED_PREFIX,
            sys.executable,
        )
        return [sys.executable]
    if vpy.is_file():
        return [str(vpy)]
    return ["python3"]


def _mask_jwt_in_log(text: str) -> str:
    text = re.sub(
        r"(ANGEL_JWT_TOKEN=)([^\s\r\n#]+)",
        r"\1***redacted***",
        text,
        flags=re.IGNORECASE,
    )
    # SmartConnect dumps full request/headers on failure — scrub before UI/logs.
    text = re.sub(r"(['\"]password['\"]\s*:\s*['\"])[^'\"]+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"(['\"]totp['\"]\s*:\s*['\"])[^'\"]+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"(X-PrivateKey['\"]\s*:\s*['\"])[^'\"]+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"(['\"]clientcode['\"]\s*:\s*['\"])[^'\"]+", r"\1***", text, flags=re.IGNORECASE)
    return text


def _humanize_angel_login_error(detail: str) -> str:
    low = (detail or "").lower()
    if "exceeding access rate" in low or "access denied because of exceeding" in low:
        return (
            "Angel rate limit — wait 15–30 minutes, then click Generate Token once. "
            "Or login on laptop and copy ANGEL_JWT_TOKEN + ANGEL_REFRESH_TOKEN into VPS backend/.env."
        )
    if "ab1050" in low or "invalid totp" in low:
        return (
            "AB1050 Invalid TOTP/client. "
            "Compare script totp= with Authenticator for that client; sync VPS clock (NTP); "
            "set ANGEL_CLIENT_PUBLIC_IP to VPS real public IP (smartapi-python hardcodes 106.193.147.98). "
            "Confirm VPS .env TOTP matches the laptop .env exactly."
        )
    if "ag8001" in low or "invalid token" in low:
        return "Angel JWT invalid — generate a fresh session after fixing credentials."
    return detail


def _clear_quote_caches() -> None:
    from app.routers import angel as angel_router

    angel_router.clear_angel_caches()


def _login_subprocess_env(root: Path) -> dict[str, str]:
    """Build child env; inject ANGEL_* from backend/.env so VPS systemd env cannot blank them."""
    env = {**os.environ}
    env_path = root / ".env"
    if not env_path.is_file():
        return env
    try:
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
    except Exception:  # noqa: BLE001
        return env
    for key, val in vals.items():
        if not key or val is None:
            continue
        text = str(val).strip()
        if not text:
            continue
        if key.startswith("ANGEL_") or key in {"JWT_SECRET", "DATABASE_URL"}:
            env[key] = text
    return env


def _format_script_failure(rc: int, stdout: str, stderr: str) -> str:
    """Surface real script failure reason (not just 'script exit 1')."""
    lines: list[str] = []
    for line in (stderr or "").splitlines() + (stdout or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # Skip SmartAPI/logzero noise that is written to stderr even on success.
        if "in pool" in s.lower():
            continue
        if re.search(r"\[I\s+\d+", s):
            continue
        lines.append(s)
    detail = " | ".join(lines[-8:]) if lines else ""
    detail = _mask_jwt_in_log(detail).strip()
    hint = _humanize_angel_login_error(detail)
    if hint and hint != detail:
        return f"script exit {rc}: {hint}"
    if detail:
        return f"script exit {rc}: {detail}"
    return (
        f"script exit {rc} (no details). "
        "On VPS: pip install -r requirements.txt in the same Python as uvicorn, "
        "and ensure ANGEL_API_KEY / ANGEL_CLIENT_ID / ANGEL_PIN / ANGEL_TOTP_SECRET are in backend/.env"
    )


def run_angel_smartapi_login_subprocess(*, reason: str) -> tuple[bool, str, str, int]:
    """
    Run angel_smartapi_login.py with a Python that has SmartAPI installed.
    Returns (success, stdout, stderr, returncode).
    Never raises — errors are captured in stderr / returncode.
    """
    root = backend_root()
    script = login_script_path(root)
    if not script.is_file():
        msg = f"missing login script (script={script})"
        LOG.error("%s Running Angel One login refresh aborted: %s", SCHED_PREFIX, msg)
        return False, "", msg, 127
    py_cmd = login_python_command(root)

    LOG.info("%s Running Angel One login refresh... (%s) py=%s", SCHED_PREFIX, reason, py_cmd[0])
    try:
        proc = subprocess.run(
            [*py_cmd, str(script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            env=_login_subprocess_env(root),
            encoding="utf-8",
            errors="replace",
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        LOG.info("%s angel_smartapi_login.py stdout:\n%s", SCHED_PREFIX, _mask_jwt_in_log(out) or "(empty)")
        if err.strip():
            LOG.info("%s angel_smartapi_login.py stderr:\n%s", SCHED_PREFIX, _mask_jwt_in_log(err) or "(empty)")
        ok = proc.returncode == 0
        if ok:
            LOG.info("%s angel_smartapi_login.py completed (exit 0)", SCHED_PREFIX)
        else:
            LOG.error(
                "%s Login refresh failed: %s",
                SCHED_PREFIX,
                _format_script_failure(proc.returncode, out, err),
            )
        return ok, out, err, proc.returncode
    except subprocess.TimeoutExpired as e:
        LOG.error("%s Login refresh failed: timeout after 120s", SCHED_PREFIX)
        return False, "", str(e), -1
    except Exception as e:  # noqa: BLE001
        LOG.exception("%s Login refresh failed: %s", SCHED_PREFIX, e)
        return False, "", str(e), -1


def apply_jwt_from_env_file() -> bool:
    """Reload JWT/refresh from backend/.env after the login script updates it."""
    from app.config import settings
    from app.services.angel_jwt_refresh import reload_angel_tokens_from_env

    changed = reload_angel_tokens_from_env()
    jwt = (settings.angel_jwt_token or "").strip()
    refresh = (settings.angel_refresh_token or "").strip()
    if not jwt:
        LOG.error("%s Login refresh failed: ANGEL_JWT_TOKEN still empty after script success", SCHED_PREFIX)
        return False
    _clear_quote_caches()
    LOG.info(
        "%s Login refresh successful (jwt len=%d, refresh set=%s, changed=%s)",
        SCHED_PREFIX,
        len(jwt),
        bool(refresh),
        changed,
    )
    return True


def apply_jwt_from_script_output(stdout: str = "") -> bool:
    """
    Compatibility wrapper: login script writes tokens into backend/.env.
    Callers historically expected JWT parsed from stdout; reload from .env instead.
    """
    _ = stdout  # retained for call-site compatibility
    return apply_jwt_from_env_file()


def _sync_login_job(reason: str, allow_retry: bool) -> None:
    ok, _stdout, _stderr, _rc = run_angel_smartapi_login_subprocess(reason=reason)
    if not ok:
        if allow_retry:
            LOG.info("%s Scheduling single retry in 5 minutes...", SCHED_PREFIX)
            schedule_retry_once()
        return
    if not apply_jwt_from_env_file():
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
    """Periodic health check: validate the JWT and auto-heal (refresh token → TOTP script)."""
    try:
        from app.services.angel_jwt_refresh import ensure_valid_angel_session

        ensure_valid_angel_session(reason="scheduler_interval")
    except Exception as e:  # noqa: BLE001
        LOG.warning("%s Scheduled JWT health check error: %s", SCHED_PREFIX, e)


def start_angel_auto_login_scheduler() -> None:
    """Start APScheduler with 00:30 daily + 08:59 Mon–Fri IST jobs. Safe to call once."""
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
        timezone=IST,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )

    async def _daily_async() -> None:
        await _async_login_job("cron_00_30", True)

    async def _premarket_async() -> None:
        await _async_login_job("cron_08_59_mon_fri", True)

    _scheduler.add_job(
        _daily_async,
        CronTrigger(hour=0, minute=30, timezone=IST),
        id=JOB_DAILY_ID,
        replace_existing=True,
    )
    _scheduler.add_job(
        _premarket_async,
        CronTrigger(hour=8, minute=59, day_of_week="mon-fri", timezone=IST),
        id=JOB_PREMARKET_ID,
        replace_existing=True,
    )
    _scheduler.add_job(
        _async_refresh_token_job,
        IntervalTrigger(minutes=20),
        id=JOB_REFRESH_ID,
        replace_existing=True,
    )
    _scheduler.start()
    LOG.info(
        "%s Angel One auto-login: 00:30 daily IST + 08:59 Mon–Fri IST; JWT health check every 20 min",
        SCHED_PREFIX,
    )


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
    Every step is verified with a real Angel quote call — success is only reported
    when the JWT actually works for market data (no more fake "token generated").
    """
    from app.services.angel_jwt_refresh import (
        reload_angel_tokens_from_env,
        try_refresh_angel_jwt_via_refresh_token,
        validate_angel_session,
    )

    # 1) Pick up tokens written by a manual script run / another strategy backend.
    reload_angel_tokens_from_env()
    usable, _detail = validate_angel_session()
    if usable:
        _clear_quote_caches()
        return {"ok": True, "message": "Angel session valid — live quotes active"}

    # 2) Lightweight refresh-token exchange, then verify it really works.
    if try_refresh_angel_jwt_via_refresh_token(reason="manual_api", force=True):
        usable, detail = validate_angel_session()
        if usable:
            return {"ok": True, "message": "Angel session refreshed (refresh token)"}
        LOG.warning("%s Refresh-token JWT still rejected: %s", SCHED_PREFIX, detail)

    # 3) Full TOTP login script.
    ok, errs = verify_angel_login_paths()
    if not ok:
        return {"ok": False, "error": "; ".join(errs)}
    ok_run, stdout, stderr, rc = run_angel_smartapi_login_subprocess(reason="manual")
    if not ok_run:
        return {
            "ok": False,
            "error": _format_script_failure(rc, stdout, stderr),
            "stderr_tail": _mask_jwt_in_log((stderr or "")[-2000:]),
        }
    if not apply_jwt_from_env_file():
        return {"ok": False, "error": "script ran but ANGEL_JWT_TOKEN was not reloaded from backend/.env"}
    usable, detail = validate_angel_session()
    if not usable:
        return {
            "ok": False,
            "error": (
                f"Token generated but Angel still rejects it: {detail}. "
                "Check ANGEL_API_KEY belongs to the same Angel app, VPS clock (NTP) and ANGEL_CLIENT_PUBLIC_IP."
            ),
        }
    return {"ok": True, "message": "Angel session refreshed and verified"}


async def trigger_manual_angel_login_async() -> dict[str, Any]:
    return await asyncio.to_thread(trigger_manual_angel_login)
