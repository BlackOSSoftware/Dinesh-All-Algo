#!/usr/bin/env python3
"""
Angel One SmartAPI — generate session (JWT + refresh + feed) using official SDK.

Uses env (see backend/.env.example):
  ANGEL_API_KEY       — SmartAPI API key (same as X-PrivateKey for quote API)
  ANGEL_CLIENT_ID     — Angel client id (login id)
  ANGEL_PIN           — 4-digit MPIN
  ANGEL_TOTP_SECRET   — TOTP secret: Base32 (A–Z, 2–7), or hex (≥16 chars), or full otpauth://… URL

Run (PowerShell):

  cd strategy-N\\backend
  .\\.venv\\Scripts\\Activate.ps1
  pip install -r requirements.txt
  python scripts\\angel_smartapi_login.py

On success, writes ANGEL_JWT_TOKEN / ANGEL_REFRESH_TOKEN (and optional feed token)
into this strategy's backend/.env only.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND_ROOT / ".env"


def _normalize_totp_secret(raw: str) -> str:
    """
    pyotp expects Base32 (A–Z, 2–7). Fix common .env issues: quotes, spaces, otpauth:// URLs.
    If the value is hex-only (even length), convert to Base32 for pyotp.
    """
    s = raw.strip().strip("\ufeff")
    # strip wrapping quotes from .env
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()

    if s.lower().startswith("otpauth://"):
        parsed = urlparse(s)
        qs = parse_qs(parsed.query)
        parts = qs.get("secret", [])
        if not parts:
            raise ValueError("otpauth URL has no secret= parameter")
        s = unquote(parts[0])

    # remove spaces / dashes (formatted display keys)
    s = "".join(s.split()).replace("-", "").upper()

    if not s:
        raise ValueError("ANGEL_TOTP_SECRET is empty after cleanup")

    # Hex seed: only when long enough to avoid mistaking a short digit string for hex.
    if len(s) >= 16 and len(s) % 2 == 0 and re.fullmatch(r"[0-9A-F]+", s):
        key = bytes.fromhex(s)
        return base64.b32encode(key).decode("ascii").rstrip("=")

    # Base32: only A-Z and 2-7 allowed (padding = optional)
    body = s.rstrip("=")
    invalid = sorted({c for c in body if c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"})
    if invalid:
        raise ValueError(
            "ANGEL_TOTP_SECRET must be Base32 (letters A–Z and digits 2–7 only), "
            "or a hex string (at least 16 hex digits). "
            f"Remove/replace these characters: {invalid!r}. "
            "If you scanned a QR, paste the otpauth://… URL or only the secret= value."
        )

    return s


def _set_env_key(text: str, key: str, value: str) -> str:
    """Replace or append KEY=value in a .env file body."""
    line = f"{key}={value}"
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
    if pattern.search(text):
        return pattern.sub(line, text)
    body = text.rstrip("\n")
    if body:
        return body + "\n" + line + "\n"
    return line + "\n"


def _write_tokens_to_env_files(jwt_token: str, refresh_token: str, feed_token: str = "") -> list[Path]:
    path = ENV_PATH
    if not path.is_file():
        print(f"skip missing: {path}")
        return []
    raw = path.read_text(encoding="utf-8")
    next_text = _set_env_key(raw, "ANGEL_JWT_TOKEN", jwt_token)
    if refresh_token:
        next_text = _set_env_key(next_text, "ANGEL_REFRESH_TOKEN", refresh_token)
    if feed_token:
        next_text = _set_env_key(next_text, "ANGEL_FEED_TOKEN", feed_token)
    if next_text != raw:
        path.write_text(next_text, encoding="utf-8", newline="\n")
    return [path]


def _login_ok(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    data = result.get("data")
    if result.get("status") is True:
        return True
    return isinstance(data, dict) and bool(data.get("jwtToken") or data.get("jwt_token"))


def _is_totp_error(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    msg = str(result.get("message") or "").lower()
    code = str(result.get("errorcode") or result.get("errorCode") or "").upper()
    return code == "AB1050" or "invalid totp" in msg


def _try_generate_session(api, client_id: str, pin: str, totp_secret: str):
    """
    Try current TOTP and nearby 30s windows — VPS clocks are often a few seconds off.
    Returns (result, totp_used).
    """
    import pyotp

    totp_obj = pyotp.TOTP(totp_secret)
    now = int(time.time())
    # Current step, then ±1 and ±2 periods (30s each).
    offsets = (0, -30, 30, -60, 60)
    last = None
    used = ""
    for off in offsets:
        code = totp_obj.at(now + off)
        used = code
        result = api.generateSession(client_id, pin, code)
        last = result
        if _login_ok(result):
            if off != 0:
                print(f"Login OK with TOTP time offset {off}s (sync VPS clock with NTP).", file=sys.stderr)
            return result, used
        # Wrong TOTP → try next window. Other errors → stop.
        if not _is_totp_error(result):
            return result, used
        time.sleep(0.35)
    return last, used


def main() -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("pip install python-dotenv", file=sys.stderr)
        return 1

    load_dotenv(BACKEND_ROOT / ".env", override=True)

    api_key = (os.getenv("ANGEL_API_KEY") or "").strip()
    client_id = (os.getenv("ANGEL_CLIENT_ID") or "").strip()
    pin = (os.getenv("ANGEL_PIN") or "").strip()
    totp_secret_raw = (os.getenv("ANGEL_TOTP_SECRET") or "").strip()

    missing = [
        n
        for n, v in (
            ("ANGEL_API_KEY", api_key),
            ("ANGEL_CLIENT_ID", client_id),
            ("ANGEL_PIN", pin),
            ("ANGEL_TOTP_SECRET", totp_secret_raw),
        )
        if not v
    ]
    if missing:
        print("Set these in backend/.env:", ", ".join(missing), file=sys.stderr)
        return 1

    try:
        totp_secret = _normalize_totp_secret(totp_secret_raw)
    except ValueError as e:
        print("ANGEL_TOTP_SECRET:", e, file=sys.stderr)
        return 1

    try:
        import pyotp
        from SmartApi.smartConnect import SmartConnect
    except ImportError as e:
        print(
            "Missing Angel login packages in this Python "
            f"({sys.executable}). Run: "
            f'"{sys.executable}" -m pip install smartapi-python pyotp logzero websocket-client python-dotenv',
            file=sys.stderr,
        )
        print(e, file=sys.stderr)
        return 1

    try:
        # Probe that secret decodes; discard value (login retries windows below).
        _ = pyotp.TOTP(totp_secret).now()
    except binascii.Error as e:
        print(
            "TOTP decode failed after normalization (Base32). "
            "Re-copy the secret from Angel (no 0/O or 1/I confusion); "
            "or paste the full otpauth:// URL from the QR export.",
            file=sys.stderr,
        )
        print(repr(e), file=sys.stderr)
        return 1

    api = SmartConnect(api_key)
    result, _totp_used = _try_generate_session(api, client_id, pin, totp_secret)

    if not isinstance(result, dict):
        print("Unexpected response:", result, file=sys.stderr)
        return 1

    if not _login_ok(result):
        if _is_totp_error(result):
            print(
                f"AB1050 for client {client_id}: Invalid TOTP/client combination. "
                "Fix backend/.env so ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET, and ANGEL_API_KEY "
                "all belong to the SAME Angel account. "
                "Get ANGEL_TOTP_SECRET from https://smartapi.angelone.in/enable-totp "
                "(secret under the QR for this client) — do not reuse another account's secret. "
                "Compare pyotp code with Google Authenticator for the same account; "
                "if they differ, the secret is wrong. Sync VPS time (NTP).",
                file=sys.stderr,
            )
        print("Login failed:", result, file=sys.stderr)
        return 1

    data = result.get("data") or {}
    jwt_raw = data.get("jwtToken") or ""
    if isinstance(jwt_raw, str) and jwt_raw.startswith("Bearer "):
        jwt_raw = jwt_raw[7:].strip()

    refresh = data.get("refreshToken") or ""
    feed = data.get("feedToken") or ""

    if not jwt_raw:
        print("Login OK but jwtToken missing:", result, file=sys.stderr)
        return 1

    updated = _write_tokens_to_env_files(jwt_raw, refresh, feed)
    print("--- OK: tokens written to backend/.env ---")
    for path in updated:
        print(f"updated: {path}")
    print()
    print(f"ANGEL_JWT_TOKEN length: {len(jwt_raw)}")
    print("Restart strategy workers after refresh so they reload .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
