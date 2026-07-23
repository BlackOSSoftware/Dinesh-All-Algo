"""Cross-process shared MCX LTP batch cache (Strategy 2 + 4 share one Angel account)."""

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
    return d / "mcx_batch_ltp.json"


def load_shared_mcx_batch(*, max_age_sec: float = 1.5) -> dict[str, dict[str, Any]] | None:
    """
    Return key -> {price, price_type, source, tradingsymbol, market_open} if fresh.
    Written by whichever strategy last successfully fetched Angel MCX quotes.
    """
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
    quotes = data.get("quotes")
    if not isinstance(quotes, dict) or not quotes:
        return None
    out: dict[str, dict[str, Any]] = {}
    for key, row in quotes.items():
        if isinstance(row, dict) and float(row.get("price") or 0) > 0:
            out[str(key).upper()] = row
    return out or None


def save_shared_mcx_batch(quotes: dict[str, dict[str, Any]]) -> None:
    if not quotes:
        return
    path = _shared_path()
    payload = {"t": time.time(), "quotes": quotes}
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
        LOG.debug("MCX shared batch saved (%d keys)", len(quotes))
    except OSError as exc:
        LOG.warning("MCX shared batch save failed: %s", exc)


def load_shared_mcx_batch_any(*, max_age_sec: float = 30.0) -> dict[str, dict[str, Any]] | None:
    """Stale-tolerant read for rate-limit fallback (still prefer memory/disk)."""
    return load_shared_mcx_batch(max_age_sec=max_age_sec)
