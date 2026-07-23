"""
Renew Angel JWT using SmartAPI refresh token (no TOTP).

POST /rest/auth/angelbroking/jwt/v1/generateTokens with {"refreshToken": "..."}
See SmartApi.smartConnect.SmartConnect.generateToken.

Also used on TokenException-style 403 from quote/candle (debounced).
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

GENERATE_TOKENS_URL = "https://apiconnect.angelone.in/rest/auth/angelbroking/jwt/v1/generateTokens"

_last_refresh_attempt_mono: float = 0.0
_REFRESH_DEBOUNCE_SEC = 90.0

_last_full_login_mono: float = 0.0
_FULL_LOGIN_DEBOUNCE_SEC = 300.0


def _is_token_error_text(text: str) -> bool:
    t = (text or "").lower()
    return (
        "invalid token" in t
        or "tokenexception" in t
        or "token is invalid" in t
        or "ag8001" in t
        or ("jwt" in t and "expired" in t)
    )


def backend_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def reload_angel_tokens_from_env() -> bool:
    """
    Re-read ANGEL_JWT_TOKEN / ANGEL_REFRESH_TOKEN from backend/.env into runtime settings.
    Picks up manual login-script updates without restarting uvicorn.
    """
    from app.config import BACKEND_ROOT, settings

    env_path = BACKEND_ROOT / ".env"
    if not env_path.is_file():
        return False

    try:
        from dotenv import dotenv_values
    except ImportError:
        return False

    vals = dotenv_values(env_path)
    jwt = (vals.get("ANGEL_JWT_TOKEN") or "").strip()
    refresh = (vals.get("ANGEL_REFRESH_TOKEN") or "").strip()
    changed = False
    if jwt and jwt != (settings.angel_jwt_token or "").strip():
        os.environ["ANGEL_JWT_TOKEN"] = jwt
        object.__setattr__(settings, "angel_jwt_token", jwt)
        changed = True
    if refresh and refresh != (settings.angel_refresh_token or "").strip():
        os.environ["ANGEL_REFRESH_TOKEN"] = refresh
        object.__setattr__(settings, "angel_refresh_token", refresh)
        changed = True
    if changed:
        LOG.info("Angel tokens reloaded from .env (jwt len=%d)", len(jwt))
    return changed


def _update_env_key(env_path: Path, key: str, value: str) -> None:
    """Insert or replace KEY=value in backend/.env (single line)."""
    line = f"{key}={value}"
    if not env_path.is_file():
        env_path.write_text(line + "\n", encoding="utf-8")
        return
    raw = env_path.read_text(encoding="utf-8")
    pat = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    if pat.search(raw):
        new_raw = pat.sub(line, raw)
    else:
        # Always one newline before a new key: rstrip() removes the file's trailing
        # newline, so "" sep would glue the new line onto the previous assignment.
        base = raw.rstrip()
        new_raw = (base + "\n" if base else "") + line + "\n"
    env_path.write_text(new_raw, encoding="utf-8")


def _apply_tokens_runtime(jwt: str, refresh: str | None) -> None:
    from app.config import settings

    j = jwt.strip()
    os.environ["ANGEL_JWT_TOKEN"] = j
    object.__setattr__(settings, "angel_jwt_token", j)
    if refresh is not None and refresh.strip():
        r = refresh.strip()
        os.environ["ANGEL_REFRESH_TOKEN"] = r
        object.__setattr__(settings, "angel_refresh_token", r)


def post_generate_tokens(
    *,
    api_key: str,
    refresh_token: str,
    source_id: str,
    client_local_ip: str,
    client_public_ip: str,
    mac_address: str,
    user_type: str,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    body = json.dumps({"refreshToken": refresh_token.strip()}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-PrivateKey": api_key.strip(),
        "X-SourceID": source_id,
        "X-ClientLocalIP": client_local_ip,
        "X-ClientPublicIP": client_public_ip,
        "X-MACAddress": mac_address,
        "X-UserType": user_type,
    }
    req = urllib.request.Request(GENERATE_TOKENS_URL, data=body, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
        text = resp.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RuntimeError("Angel token refresh: non-object JSON")
        return data


def try_refresh_angel_jwt_via_refresh_token(*, reason: str, force: bool = False) -> bool:
    """
    If ANGEL_REFRESH_TOKEN is set, exchange it for a new JWT (and rotated refresh if present).
    Updates .env + in-memory settings and clears Angel caches. Debounced unless force=True.
    """
    global _last_refresh_attempt_mono
    from app.config import settings

    from app.services.angel_upstream_gate import acquire_angel_upstream_slot

    api_key = (settings.angel_api_key or "").strip()
    refresh = (settings.angel_refresh_token or "").strip()
    if not api_key or not refresh:
        LOG.debug("Angel JWT refresh skipped (%s): missing api_key or refresh token", reason)
        return False

    now = time.monotonic()
    if not force and now - _last_refresh_attempt_mono < _REFRESH_DEBOUNCE_SEC:
        LOG.debug("Angel JWT refresh debounced (%s)", reason)
        return False
    from app.services.angel_upstream_gate import recent_angel_jwt_refresh

    if not force and recent_angel_jwt_refresh(max_age_sec=_REFRESH_DEBOUNCE_SEC):
        LOG.debug("Angel JWT refresh skipped — recent shared refresh (%s)", reason)
        reload_angel_tokens_from_env()
        return bool((settings.angel_jwt_token or "").strip())
    _last_refresh_attempt_mono = now

    acquire_angel_upstream_slot()
    try:
        raw = post_generate_tokens(
            api_key=api_key,
            refresh_token=refresh,
            source_id=(settings.angel_source_id or "WEB").strip(),
            client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
            client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
            mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
            user_type=(settings.angel_user_type or "USER").strip(),
            timeout_sec=float(settings.angel_request_timeout_sec or 20.0),
        )
    except Exception as e:  # noqa: BLE001
        LOG.warning("Angel JWT refresh failed (%s): %s", reason, e)
        return False

    if not raw.get("status") and not raw.get("data"):
        LOG.warning("Angel JWT refresh bad payload (%s): %s", reason, str(raw)[:500])
        return False

    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    jwt_raw = data.get("jwtToken") or data.get("jwt_token") or ""
    if isinstance(jwt_raw, str) and jwt_raw.startswith("Bearer "):
        jwt_raw = jwt_raw[7:].strip()
    if not jwt_raw:
        LOG.warning("Angel JWT refresh: no jwtToken in response (%s)", reason)
        return False

    new_refresh = data.get("refreshToken") or data.get("refresh_token") or refresh

    env_path = backend_root() / ".env"
    try:
        _update_env_key(env_path, "ANGEL_JWT_TOKEN", jwt_raw)
        if new_refresh:
            _update_env_key(env_path, "ANGEL_REFRESH_TOKEN", str(new_refresh).strip())
    except OSError as e:
        LOG.error("Angel JWT refresh: could not write .env: %s", e)
        return False

    _apply_tokens_runtime(jwt_raw, str(new_refresh).strip() if new_refresh else None)

    try:
        from app.routers import angel as angel_router

        angel_router.clear_angel_caches()
    except Exception:  # noqa: BLE001
        pass

    LOG.info("Angel JWT refreshed via refresh token (%s); len(jwt)=%d", reason, len(jwt_raw))
    from app.services.angel_upstream_gate import note_angel_jwt_refreshed, note_angel_jwt_validated

    note_angel_jwt_refreshed(reason=reason)
    note_angel_jwt_validated()
    return True


def parse_angel_refresh_from_login_stdout(stdout: str) -> str | None:
    for line in stdout.splitlines():
        s = line.strip()
        if s.upper().startswith("ANGEL_REFRESH_TOKEN="):
            val = s.split("=", 1)[1].strip().strip('"').strip("'")
            if val and not val.startswith("#"):
                return val
    return None


def save_refresh_token_to_env_and_runtime(refresh: str) -> None:
    from app.config import settings

    r = refresh.strip()
    if not r:
        return
    env_path = backend_root() / ".env"
    _update_env_key(env_path, "ANGEL_REFRESH_TOKEN", r)
    os.environ["ANGEL_REFRESH_TOKEN"] = r
    object.__setattr__(settings, "angel_refresh_token", r)


def validate_angel_session() -> tuple[bool, str]:
    """
    Verify the current JWT with a real quote call (SENSEX index token — works on any session).
    Returns (usable, detail). Only a token-style rejection marks the session unusable;
    rate limits / network errors are treated as usable so we don't relogin needlessly.

    Skips the quote probe when another strategy backend validated recently (shared stamp),
    so 4 schedulers do not burn Angel's rate budget on health checks.
    """
    from app.config import settings
    from app.services.angel_quote import post_market_quote, _truthy_status
    from app.services.angel_upstream_gate import note_angel_jwt_validated, recent_angel_jwt_validated

    api_key = (settings.angel_api_key or "").strip()
    jwt = (settings.angel_jwt_token or "").strip()
    if not api_key or not jwt:
        return False, "ANGEL_API_KEY or ANGEL_JWT_TOKEN missing"

    if recent_angel_jwt_validated(max_age_sec=480.0):
        LOG.debug("Angel JWT validate skipped — recent shared validation stamp")
        return True, "ok (shared recent validate)"

    try:
        raw = post_market_quote(
            api_key=api_key,
            jwt_token=jwt,
            source_id=(settings.angel_source_id or "WEB").strip(),
            client_local_ip=(settings.angel_client_local_ip or "127.0.0.1").strip(),
            client_public_ip=(settings.angel_client_public_ip or "127.0.0.1").strip(),
            mac_address=(settings.angel_mac_address or "00:00:00:00:00:00").strip(),
            user_type=(settings.angel_user_type or "USER").strip(),
            mode="LTP",
            exchange_tokens={"BSE": ["99919000"]},
            timeout_sec=8.0,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if _is_token_error_text(msg):
            return False, msg[:300]
        return True, f"non-token error ignored: {msg[:200]}"

    msg = str(raw.get("message") or raw.get("Message") or "") if isinstance(raw, dict) else ""
    if _truthy_status(raw):
        note_angel_jwt_validated()
        return True, "ok"
    if _is_token_error_text(msg):
        return False, msg[:300]
    return True, f"non-token status ignored: {msg[:200]}"


def ensure_valid_angel_session(*, reason: str, force: bool = False) -> bool:
    """
    Auto-heal the Angel session:
      1. Reload tokens from backend/.env (picks up manual script runs).
      2. Validate the current JWT with a real quote call — if usable, done.
      3. Refresh-token exchange, then re-validate.
      4. Full TOTP login script (debounced), then re-validate.
    Returns True only when a JWT that Angel actually accepts is in place.
    """
    global _last_full_login_mono

    reload_angel_tokens_from_env()

    ok, detail = validate_angel_session()
    if ok:
        return True
    LOG.warning("Angel session invalid (%s): %s — auto-healing", reason, detail)

    if try_refresh_angel_jwt_via_refresh_token(reason=reason, force=True):
        ok, detail = validate_angel_session()
        if ok:
            LOG.info("Angel session restored via refresh token (%s)", reason)
            return True
        LOG.warning("Angel refresh-token JWT still rejected (%s): %s", reason, detail)

    now = time.monotonic()
    if not force and now - _last_full_login_mono < _FULL_LOGIN_DEBOUNCE_SEC:
        LOG.debug("Angel full login debounced (%s)", reason)
        return False
    _last_full_login_mono = now

    try:
        from app.services.angel_auto_login_scheduler import (
            apply_jwt_from_env_file,
            run_angel_smartapi_login_subprocess,
        )

        ok_run, _stdout, _stderr, _rc = run_angel_smartapi_login_subprocess(reason=reason)
        if ok_run and apply_jwt_from_env_file():
            ok, detail = validate_angel_session()
            if ok:
                LOG.info("Angel session restored via TOTP login script (%s)", reason)
                return True
            LOG.error("Angel TOTP login produced a JWT that is still rejected (%s): %s", reason, detail)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Angel TOTP login failed (%s): %s", reason, exc)
    return False
