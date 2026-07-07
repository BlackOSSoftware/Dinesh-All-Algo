#!/usr/bin/env python3
"""Import or refresh StocksRin session via login API."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.stocksrin.cookie_store import import_session_payload, session_file_path
from app.services.stocksrin.header_provider import normalize_authorization
from app.services.stocksrin.login_client import login
from app.services.stocksrin.session_manager import get_session_manager, reset_session_manager


def _parse_env() -> dict[str, str]:
    out: dict[str, str] = {}
    env_path = BACKEND / ".env"
    if not env_path.is_file():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="StocksRin session import / login")
    parser.add_argument("--file", type=Path, help="JSON with user + optional authorization")
    parser.add_argument("--login", action="store_true", help="Login via STOCKSRIN_EMAIL + PASSWORD in .env")
    parser.add_argument("--from-env", action="store_true", help="Legacy: import user + app auth from .env")
    args = parser.parse_args()

    env = _parse_env()

    if args.login or (not args.file and not args.from_env):
        email = env.get("STOCKSRIN_EMAIL", "")
        pwd = env.get("STOCKSRIN_PASSWORD_B64", "")
        if not pwd and env.get("STOCKSRIN_PASSWORD"):
            pwd = base64.b64encode(env["STOCKSRIN_PASSWORD"].encode()).decode()
        if not email or not pwd:
            print("Set STOCKSRIN_EMAIL and STOCKSRIN_PASSWORD_B64 in .env")
            return 1
        result = login(email=email, password_b64=pwd)
        from app.services.stocksrin.cookie_store import StocksRinSession, save_session
        from app.services.stocksrin.header_provider import app_authorization

        sess = StocksRinSession(
            authorization=app_authorization(None),
            user=result["user_id"],
            jwt_token=result["token"],
            source="login_cli",
        )
        save_session(sess)
    elif args.from_env:
        import_session_payload(
            {
                "authorization": normalize_authorization(
                    env.get("STOCKSRIN_APP_AUTHORIZATION") or env.get("STOCKSRIN_AUTHORIZATION", "")
                ),
                "user": env.get("STOCKSRIN_USER", ""),
            },
            source="env_import",
        )
    elif args.file:
        raw = json.loads(args.file.read_text(encoding="utf-8"))
        import_session_payload(raw, source=f"file:{args.file.name}")

    reset_session_manager()
    mgr = get_session_manager()
    ok = mgr.validate(force=True)
    print(json.dumps({
        "ok": ok,
        "savedTo": str(session_file_path()),
        "user": mgr.session.user if mgr.session else "",
        "validated": ok,
    }, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
