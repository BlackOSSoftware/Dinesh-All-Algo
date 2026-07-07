"""Resolve MCX commodity futures tokens from Angel SmartAPI."""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT, settings
from app.services.angel_orders import search_scrip

LOG = logging.getLogger(__name__)

_CACHE_PATH = BACKEND_ROOT / "instance" / "mcx_tokens_cache.json"
_CACHE_TTL_SEC = 6 * 3600  # 6 hours

_MCX_LOOKUP: dict[str, dict[str, str]] = {
    "CRUDE_OIL": {"search": "CRUDEOIL", "symbol": "CRUDEOIL"},
    "NATURAL_GAS": {"search": "NATURALGAS", "symbol": "NATURALGAS"},
    "SILVER_MICRO": {"search": "SILVERMIC", "symbol": "SILVERMIC"},
}

_SCRIP_MASTER_URLS = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
)


def _parse_expiry(value: str) -> datetime | None:
    raw = (value or "").strip().upper()
    if not raw:
        return None
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d%b%y", "%d-%b-%y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})([A-Z]{3})(\d{2,4})", raw)
    if not m:
        return None
    day, mon, yr = m.groups()
    yr = yr if len(yr) == 4 else f"20{yr}"
    try:
        return datetime.strptime(f"{day}{mon}{yr}", "%d%b%Y")
    except ValueError:
        return None


def _expiry_from_symbol(symbol: str) -> datetime | None:
    s = (symbol or "").upper()
    m = re.search(r"(\d{1,2}[A-Z]{3}\d{2,4})", s)
    if not m:
        return None
    return _parse_expiry(m.group(1))


def _is_front_future_row(row: dict[str, Any], base_symbol: str) -> bool:
    sym = str(row.get("tradingsymbol") or row.get("symbol") or "").upper()
    name = str(row.get("name") or row.get("symbolname") or "").upper()
    if base_symbol not in sym and base_symbol not in name:
        return False
    if "CRUDEOILM" in sym or "NATGASMINI" in sym:
        return False
    inst = str(row.get("instrumenttype") or "").upper()
    if inst and inst not in ("FUTCOM", "FUT"):
        return False
    return "FUT" in sym or inst in ("FUTCOM", "FUT")


def _pick_front_month(rows: list[dict[str, Any]], base_symbol: str) -> dict[str, Any] | None:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if not _is_front_future_row(row, base_symbol):
            continue
        sym = str(row.get("tradingsymbol") or row.get("symbol") or "")
        exp = _parse_expiry(str(row.get("expiry") or "")) or _expiry_from_symbol(sym)
        if exp is None:
            continue
        if exp >= today:
            candidates.append((exp, row))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _row_to_payload(key: str, row: dict[str, Any]) -> dict[str, str]:
    labels = {
        "CRUDE_OIL": "Crude Oil",
        "NATURAL_GAS": "Natural Gas",
        "SILVER_MICRO": "Silver Micro",
    }
    default_lots = {
        "CRUDE_OIL": "10",
        "NATURAL_GAS": "1250",
        "SILVER_MICRO": "1",
    }
    label = labels.get(key, key.replace("_", " ").title())
    token = str(row.get("symboltoken") or row.get("token") or "").strip()
    tradingsymbol = str(row.get("tradingsymbol") or row.get("symbol") or "").strip()
    lotsize = str(row.get("lotsize") or default_lots.get(key, "1"))
    return {
        "key": key,
        "label": label,
        "exchange": "MCX",
        "token": token,
        "tradingsymbol": tradingsymbol,
        "lotsize": lotsize,
    }


def _load_disk_cache() -> dict[str, Any]:
    if not _CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_disk_cache(data: dict[str, Any]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _cached_entry(key: str) -> dict[str, str] | None:
    cache = _load_disk_cache()
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return None
    ts = float(entry.get("_ts") or 0)
    if time.time() - ts > _CACHE_TTL_SEC:
        return None
    payload = {k: str(v) for k, v in entry.items() if not k.startswith("_") and v}
    if payload.get("token") and payload.get("tradingsymbol"):
        return payload
    return None


def _store_cache(key: str, payload: dict[str, str]) -> None:
    cache = _load_disk_cache()
    cache[key] = {**payload, "_ts": time.time()}
    _save_disk_cache(cache)


def _angel_headers() -> dict[str, str]:
    return {
        "api_key": settings.angel_api_key.strip(),
        "jwt_token": settings.angel_jwt_token.strip(),
        "source_id": settings.angel_source_id,
        "client_local_ip": settings.angel_client_local_ip,
        "client_public_ip": settings.angel_client_public_ip,
        "mac_address": settings.angel_mac_address,
        "user_type": settings.angel_user_type,
    }


def _resolve_via_search(key: str) -> dict[str, str] | None:
    if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
        return None
    meta = _MCX_LOOKUP.get(key)
    if not meta:
        return None
    try:
        raw = search_scrip(
            exchange="MCX",
            searchscrip=meta["search"],
            timeout_sec=float(settings.angel_request_timeout_sec or 15.0),
            **_angel_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("MCX searchScrip failed for %s: %s", key, exc)
        return None
    rows = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return None
    picked = _pick_front_month([r for r in rows if isinstance(r, dict)], meta["symbol"])
    if not picked:
        return None
    payload = _row_to_payload(key, picked)
    if payload.get("token") and payload.get("tradingsymbol"):
        _store_cache(key, payload)
        return payload
    return None


def _download_scrip_master() -> list[dict[str, Any]]:
    ctx = ssl.create_default_context()
    for url in _SCRIP_MASTER_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "strategy4/1.0"})
            with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
            LOG.warning("Scrip master download failed %s: %s", url, exc)
    return []


def _resolve_via_master(key: str) -> dict[str, str] | None:
    meta = _MCX_LOOKUP.get(key)
    if not meta:
        return None
    rows = [
        r
        for r in _download_scrip_master()
        if str(r.get("exch_seg") or "").upper() == "MCX"
        and str(r.get("name") or "").upper() == meta["symbol"]
    ]
    picked = _pick_front_month(rows, meta["symbol"])
    if not picked:
        return None
    payload = _row_to_payload(key, picked)
    if payload.get("token") and payload.get("tradingsymbol"):
        _store_cache(key, payload)
        return payload
    return None


def resolve_mcx_instrument(key: str) -> dict[str, str] | None:
    """Return token/tradingsymbol for supported MCX markets (cached)."""
    k = (key or "").strip().upper()
    cached = _cached_entry(k)
    if cached:
        return cached
    payload = _resolve_via_search(k) or _resolve_via_master(k)
    if payload:
        LOG.info("Resolved MCX %s → %s (%s)", k, payload.get("tradingsymbol"), payload.get("token"))
    return payload
