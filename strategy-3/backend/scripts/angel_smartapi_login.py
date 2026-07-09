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
        print("pip install smartapi-python pyotp logzero websocket-client", file=sys.stderr)
        print(e, file=sys.stderr)
        return 1

    try:
        totp = pyotp.TOTP(totp_secret).now()
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
    result = api.generateSession(client_id, pin, totp)

    if not isinstance(result, dict):
        print("Unexpected response:", result, file=sys.stderr)
        return 1

    if result.get("status") is not True and not result.get("data"):
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
