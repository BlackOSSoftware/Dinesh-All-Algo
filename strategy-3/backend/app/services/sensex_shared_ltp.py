"""Cross-process shared SENSEX LTP cache (Strategy 1 + 3 share one Angel account)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _shared_path() -> Path:
    d = _repo_root() / ".angel_shared"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sensex_ltp.json"


def load_shared_sensex_ltp(*, max_age_sec: float = 1.5) -> tuple[float, dict[str, Any]] | None:
    """Return (ltp, payload) if a sibling strategy fetched a fresh live quote."""
    path = _shared_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    ts = float(data.get("t") or 0.0)
    if ts <= 0 or (time.time() - ts) > max_age_sec:
        return None
    try:
        ltp = float(data.get("ltp") or 0)
    except (TypeError, ValueError):
        return None
    if ltp <= 0:
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        payload = {
            "quote_source": "live",
            "angel_ok": True,
            "fetched": [{"ltp": ltp, "symbolToken": "99919000"}],
        }
    return ltp, payload


def save_shared_sensex_ltp(ltp: float, payload: dict[str, Any] | None = None) -> None:
    if ltp <= 0:
        return
    path = _shared_path()
    body = {"t": time.time(), "ltp": float(ltp), "payload": payload or {}}
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(body), encoding="utf-8")
        tmp.replace(path)
        LOG.debug("SENSEX shared LTP saved=%.2f", ltp)
    except OSError as exc:
        LOG.warning("SENSEX shared LTP save failed: %s", exc)
