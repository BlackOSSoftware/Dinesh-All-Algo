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
_EXPIRIES_CACHE_PATH = BACKEND_ROOT / "instance" / "mcx_expiries_cache.json"
_CACHE_TTL_SEC = 6 * 3600  # 6 hours
_EXPIRIES_CACHE_TTL_SEC = 300  # 5 minutes
_FAIL_CACHE_TTL_SEC = 90.0
_SEARCH_FAIL_UNTIL: dict[str, float] = {}
_MASTER_DOWNLOAD_FAIL_UNTIL: float = 0.0
_MASTER_DOWNLOAD_COOLDOWN_SEC = 300.0

_SCRIP_MASTER_CACHE: list[dict[str, Any]] | None = None
_SCRIP_MASTER_CACHE_TS: float = 0.0

_MCX_LOOKUP: dict[str, dict[str, str]] = {
    "CRUDE_OIL": {"search": "CRUDEOIL", "symbol": "CRUDEOIL", "variant": "standard"},
    "CRUDE_OIL_MINI": {"search": "CRUDEOILM", "symbol": "CRUDEOILM", "variant": "mini"},
    "CRUDE_OIL_MEGA": {"search": "CRUDEOIL", "symbol": "CRUDEOIL", "variant": "standard"},
    "NATURAL_GAS": {"search": "NATURALGAS", "symbol": "NATURALGAS", "variant": "standard"},
    "NATURAL_GAS_MINI": {"search": "NATGASMINI", "symbol": "NATGASMINI", "variant": "mini"},
    "NATURAL_GAS_MEGA": {"search": "NATURALGAS", "symbol": "NATURALGAS", "variant": "standard"},
    "SILVER_MICRO": {"search": "SILVERMIC", "symbol": "SILVERMIC", "variant": "micro"},
    "SILVER_MINI": {"search": "SILVERM", "symbol": "SILVERM", "variant": "mini"},
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


def _is_front_future_row(row: dict[str, Any], base_symbol: str, *, variant: str = "standard") -> bool:
    sym = str(row.get("tradingsymbol") or row.get("symbol") or "").upper()
    name = str(row.get("name") or row.get("symbolname") or "").upper()
    if base_symbol not in sym and base_symbol not in name:
        return False
    if sym.endswith("CE") or sym.endswith("PE"):
        return False
    if variant == "mini":
        if base_symbol == "CRUDEOILM" and "CRUDEOILM" not in sym:
            return False
        if base_symbol == "NATGASMINI" and "NATGASMINI" not in sym:
            return False
        if base_symbol == "SILVERM" and ("SILVERM" not in sym or "SILVERMIC" in sym):
            return False
    elif variant == "micro":
        if "SILVERMIC" not in sym:
            return False
    else:
        if "CRUDEOILM" in sym or "NATGASMINI" in sym or "SILVERMIC" in sym:
            return False
    inst = str(row.get("instrumenttype") or "").upper()
    if inst and inst not in ("FUTCOM", "FUT"):
        return False
    if sym.endswith("FUT"):
        return True
    return inst in ("FUTCOM", "FUT")


def _rows_from_search(key: str, meta: dict[str, str]) -> list[dict[str, Any]]:
    if not settings.angel_api_key.strip() or not settings.angel_jwt_token.strip():
        return []
    fail_until = _SEARCH_FAIL_UNTIL.get(key, 0.0)
    if time.time() < fail_until:
        return []
    try:
        raw = search_scrip(
            exchange="MCX",
            searchscrip=meta["search"],
            timeout_sec=min(8.0, float(settings.angel_request_timeout_sec or 15.0)),
            **_angel_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("MCX searchScrip failed for %s: %s", key, exc)
        _SEARCH_FAIL_UNTIL[key] = time.time() + _FAIL_CACHE_TTL_SEC
        return []
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    seen_syms: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        if not _is_front_future_row(row, meta["symbol"], variant=meta.get("variant", "standard")):
            continue
        sym = str(row.get("tradingsymbol") or row.get("symbol") or "").strip().upper()
        if not sym or sym in seen_syms:
            continue
        seen_syms.add(sym)
        rows.append(row)
    return rows


def _collect_future_rows(key: str, *, allow_master: bool = True) -> list[dict[str, Any]]:
    meta = _MCX_LOOKUP.get(key)
    if not meta:
        return []

    rows = _rows_from_search(key, meta)
    if rows:
        return rows
    if not allow_master:
        return []

    master_rows = [
        r
        for r in _get_scrip_master_cached()
        if str(r.get("exch_seg") or r.get("exchange") or "").upper() == "MCX"
        and str(r.get("name") or r.get("symbol") or "").upper() == meta["symbol"]
    ]
    out: list[dict[str, Any]] = []
    seen_syms: set[str] = set()
    for row in master_rows:
        if not _is_front_future_row(row, meta["symbol"], variant=meta.get("variant", "standard")):
            continue
        sym = str(row.get("tradingsymbol") or row.get("symbol") or "").strip().upper()
        if not sym or sym in seen_syms:
            continue
        seen_syms.add(sym)
        out.append(row)
    return out


def _row_expiry(row: dict[str, Any]) -> datetime | None:
    sym = str(row.get("tradingsymbol") or row.get("symbol") or "")
    return _parse_expiry(str(row.get("expiry") or "")) or _expiry_from_symbol(sym)


def _expiry_payload(key: str, row: dict[str, Any], exp: datetime) -> dict[str, str]:
    base = _row_to_payload(key, row)
    return {
        **base,
        "expiry": exp.strftime("%Y-%m-%d"),
        "expiryLabel": exp.strftime("%d %b %Y").upper(),
    }


def _load_expiries_disk_cache(key: str) -> list[dict[str, str]] | None:
    if not _EXPIRIES_CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(_EXPIRIES_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    ts = float(entry.get("_ts") or 0)
    if time.time() - ts > _EXPIRIES_CACHE_TTL_SEC:
        return None
    rows = entry.get("rows")
    if not isinstance(rows, list):
        return None
    out = [r for r in rows if isinstance(r, dict) and r.get("expiry") and r.get("tradingsymbol")]
    return out or None


def _load_expiries_disk_cache_any(key: str) -> list[dict[str, str]] | None:
    """Return expiry rows even if TTL expired (dashboard / rate-limit fallback)."""
    if not _EXPIRIES_CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(_EXPIRIES_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    rows = entry.get("rows")
    if not isinstance(rows, list):
        return None
    out = [r for r in rows if isinstance(r, dict) and r.get("expiry") and r.get("tradingsymbol")]
    return out or None


def _save_expiries_disk_cache(key: str, rows: list[dict[str, str]]) -> None:
    cache: dict[str, Any] = {}
    if _EXPIRIES_CACHE_PATH.is_file():
        try:
            loaded = json.loads(_EXPIRIES_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cache = loaded
        except (OSError, json.JSONDecodeError):
            cache = {}
    cache[key] = {"_ts": time.time(), "rows": rows}
    _EXPIRIES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _EXPIRIES_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def list_mcx_future_expiries(key: str, *, include_expired: bool = False) -> list[dict[str, str]]:
    """List MCX futures contracts for a market, sorted by expiry ascending."""
    k = (key or "").strip().upper()
    cache_key = f"{k}:{'all' if include_expired else 'live'}"
    cached = _load_expiries_disk_cache(cache_key)
    if cached:
        return cached
    # Prefer any stale expiry cache over slow Angel/master fallbacks (keeps UI responsive).
    stale = _load_expiries_disk_cache_any(cache_key) or _load_expiries_disk_cache_any(f"{k}:all")
    if stale:
        return stale

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in _collect_future_rows(k, allow_master=False):
        exp = _row_expiry(row)
        if exp is None:
            continue
        if not include_expired and exp < today:
            continue
        candidates.append((exp, row))
    candidates.sort(key=lambda x: x[0])
    out = [_expiry_payload(k, row, exp) for exp, row in candidates]
    if not out and not include_expired:
        out = list_mcx_future_expiries(k, include_expired=True)
        cache_key = f"{k}:all"
    if not out:
        # Last resort: master download (slow) — only when nothing cached.
        for row in _collect_future_rows(k, allow_master=True):
            exp = _row_expiry(row)
            if exp is None:
                continue
            if not include_expired and exp < today:
                continue
            candidates.append((exp, row))
        candidates.sort(key=lambda x: x[0])
        out = [_expiry_payload(k, row, exp) for exp, row in candidates]
    if out:
        _save_expiries_disk_cache(cache_key, out)
    return out


def peek_cached_symbol_for_expiry(key: str, expiry_iso: str) -> str:
    """Fast disk-only lookup for dashboard symbol label (never hits Angel)."""
    k = (key or "").strip().upper()
    target = (expiry_iso or "").strip()[:10]
    if not k or not target:
        return ""
    for cache_key in (f"{k}:live", f"{k}:all"):
        rows = _load_expiries_disk_cache_any(cache_key) or []
        for row in rows:
            if str(row.get("expiry") or "")[:10] == target:
                return str(row.get("tradingsymbol") or "").strip()
    return ""


def resolve_mcx_instrument_for_expiry(key: str, expiry_iso: str) -> dict[str, str] | None:
    """Resolve a specific MCX futures contract by expiry date (YYYY-MM-DD)."""
    k = (key or "").strip().upper()
    target_text = (expiry_iso or "").strip()[:10]
    if not target_text:
        return None
    try:
        target = datetime.strptime(target_text, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return None
    # Prefer expiry disk cache (fast) before live Angel calls.
    for cache_key in (f"{k}:live", f"{k}:all"):
        for row in _load_expiries_disk_cache_any(cache_key) or []:
            if str(row.get("expiry") or "")[:10] != target_text:
                continue
            if row.get("token") and row.get("tradingsymbol"):
                return {k2: str(v) for k2, v in row.items()}
    for row in _collect_future_rows(k, allow_master=False):
        exp = _row_expiry(row)
        if exp is None:
            continue
        if exp.date() == target.date():
            payload = _expiry_payload(k, row, exp)
            if payload.get("token") and payload.get("tradingsymbol"):
                return payload
    return None


def _pick_front_month(rows: list[dict[str, Any]], base_symbol: str, *, variant: str = "standard") -> dict[str, Any] | None:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if not _is_front_future_row(row, base_symbol, variant=variant):
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
        "CRUDE_OIL_MINI": "Crude Oil Mini",
        "CRUDE_OIL_MEGA": "Crude Oil Mega",
        "NATURAL_GAS": "Natural Gas",
        "NATURAL_GAS_MINI": "Natural Gas Mini",
        "NATURAL_GAS_MEGA": "Natural Gas Mega",
        "SILVER_MICRO": "Silver Micro",
        "SILVER_MINI": "Silver Mini",
    }
    default_lots = {
        "CRUDE_OIL": "10",
        "CRUDE_OIL_MINI": "10",
        "CRUDE_OIL_MEGA": "100",
        "NATURAL_GAS": "1250",
        "NATURAL_GAS_MINI": "250",
        "NATURAL_GAS_MEGA": "1250",
        "SILVER_MICRO": "1",
        "SILVER_MINI": "5",
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


def _stale_cached_entry(key: str) -> dict[str, str] | None:
    """Return disk token even if TTL expired (keeps quotes/dashboard alive under Angel rate limits)."""
    cache = _load_disk_cache()
    entry = cache.get(key)
    if not isinstance(entry, dict):
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
    if time.time() < _SEARCH_FAIL_UNTIL.get(key, 0.0):
        return None
    meta = _MCX_LOOKUP.get(key)
    if not meta:
        return None
    try:
        raw = search_scrip(
            exchange="MCX",
            searchscrip=meta["search"],
            timeout_sec=min(8.0, float(settings.angel_request_timeout_sec or 15.0)),
            **_angel_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("MCX searchScrip failed for %s: %s", key, exc)
        _SEARCH_FAIL_UNTIL[key] = time.time() + _FAIL_CACHE_TTL_SEC
        return None
    rows = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return None
    picked = _pick_front_month(
        [r for r in rows if isinstance(r, dict)],
        meta["symbol"],
        variant=meta.get("variant", "standard"),
    )
    if not picked:
        return None
    payload = _row_to_payload(key, picked)
    if payload.get("token") and payload.get("tradingsymbol"):
        _store_cache(key, payload)
        return payload
    return None


def _download_scrip_master() -> list[dict[str, Any]]:
    global _MASTER_DOWNLOAD_FAIL_UNTIL
    if time.time() < _MASTER_DOWNLOAD_FAIL_UNTIL:
        return []
    ctx = ssl.create_default_context()
    for url in _SCRIP_MASTER_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "strategy2/1.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
            LOG.warning("Scrip master download failed %s: %s", url, exc)
    _MASTER_DOWNLOAD_FAIL_UNTIL = time.time() + _MASTER_DOWNLOAD_COOLDOWN_SEC
    return []


def _get_scrip_master_cached() -> list[dict[str, Any]]:
    global _SCRIP_MASTER_CACHE, _SCRIP_MASTER_CACHE_TS
    if _SCRIP_MASTER_CACHE is not None and time.time() - _SCRIP_MASTER_CACHE_TS < _CACHE_TTL_SEC:
        return _SCRIP_MASTER_CACHE
    rows = _download_scrip_master()
    if rows:
        _SCRIP_MASTER_CACHE = rows
        _SCRIP_MASTER_CACHE_TS = time.time()
        return rows
    # Keep previous in-memory master if download failed.
    return _SCRIP_MASTER_CACHE or []


def _resolve_via_master(key: str) -> dict[str, str] | None:
    meta = _MCX_LOOKUP.get(key)
    if not meta:
        return None
    rows = [
        r
        for r in _get_scrip_master_cached()
        if str(r.get("exch_seg") or "").upper() == "MCX"
        and str(r.get("name") or "").upper() == meta["symbol"]
    ]
    picked = _pick_front_month(rows, meta["symbol"], variant=meta.get("variant", "standard"))
    if not picked:
        return None
    payload = _row_to_payload(key, picked)
    if payload.get("token") and payload.get("tradingsymbol"):
        _store_cache(key, payload)
        return payload
    return None


def resolve_mcx_instrument(key: str, *, allow_slow: bool = False) -> dict[str, str] | None:
    """Return token/tradingsymbol for supported MCX markets (cached).

    Hot paths (dashboard quotes) should keep allow_slow=False so Angel rate limits
    cannot block the API worker on scrip-master downloads.
    """
    k = (key or "").strip().upper()
    cached = _cached_entry(k) or _stale_cached_entry(k)
    if cached:
        return cached
    payload = _resolve_via_search(k)
    if payload:
        LOG.info("Resolved MCX %s → %s (%s)", k, payload.get("tradingsymbol"), payload.get("token"))
        return payload
    stale = _stale_cached_entry(k)
    if stale:
        return stale
    if not allow_slow:
        return None
    payload = _resolve_via_master(k)
    if payload:
        LOG.info("Resolved MCX %s → %s (%s)", k, payload.get("tradingsymbol"), payload.get("token"))
    return payload
