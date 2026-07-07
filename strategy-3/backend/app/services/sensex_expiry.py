"""SENSEX BFO weekly expiry — auto-detect from instruments / Angel scrip master."""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT, settings
from app.services.nse_trading_calendar import resolve_session_expiry_date

LOG = logging.getLogger(__name__)

_CACHE_PATH = BACKEND_ROOT / "instance" / "sensex_expiry_cache.json"
_CACHE_TTL_SEC = 6 * 3600

_SCRIP_MASTER_URLS = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
)

_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _parse_expiry(value: str) -> datetime | None:
    raw = (value or "").strip().upper()
    if not raw:
        return None
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d%b%y", "%d-%b-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:11] if fmt != "%Y-%m-%d" else raw[:10], fmt)
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


def _parse_bfo_instruments() -> list[dict[str, Any]]:
    raw = (settings.angel_bfo_instruments_json or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict) and isinstance(data.get("instruments"), list):
        return [r for r in data["instruments"] if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _is_sensex_option_row(row: dict[str, Any]) -> bool:
    exch = str(row.get("exch_seg") or row.get("exchange") or "").upper()
    if exch and "BFO" not in exch and "BSE_FO" not in exch:
        return False
    sym = str(row.get("tradingsymbol") or row.get("symbol") or "").upper()
    name = str(row.get("name") or row.get("symbolname") or "").upper()
    if "SENSEX" not in sym and "SENSEX" not in name:
        return False
    return True


def _fetch_scrip_master_rows() -> list[dict[str, Any]]:
    ctx = ssl.create_default_context()
    for url in _SCRIP_MASTER_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "strategy-3/1.0"})
            with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            LOG.warning("Scrip master fetch failed (%s): %s", url, exc)
    return []


def _load_disk_cache() -> dict[str, Any]:
    if not _CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_disk_cache(expiry_dates: list[str], source: str) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(
        json.dumps({"_ts": time.time(), "source": source, "expiryDates": expiry_dates}, indent=2),
        encoding="utf-8",
    )


def _collect_expiry_datetimes() -> tuple[list[datetime], str]:
    found: set[datetime] = set()
    source_parts: list[str] = []

    for row in _parse_bfo_instruments():
        sym = str(row.get("tradingsymbol") or row.get("symbol") or "")
        exp = _parse_expiry(str(row.get("expiry") or row.get("expirydate") or "")) or _expiry_from_symbol(sym)
        if exp:
            found.add(exp.replace(hour=0, minute=0, second=0, microsecond=0))

    if found:
        source_parts.append("bfo_instruments")

    cache = _load_disk_cache()
    cache_ts = float(cache.get("_ts") or 0)
    cached_dates = cache.get("expiryDates") if isinstance(cache.get("expiryDates"), list) else []

    if time.time() - cache_ts < _CACHE_TTL_SEC and cached_dates:
        for d in cached_dates:
            parsed = _parse_expiry(str(d))
            if parsed:
                found.add(parsed.replace(hour=0, minute=0, second=0, microsecond=0))
        if cached_dates:
            source_parts.append("cache")

    if time.time() - cache_ts >= _CACHE_TTL_SEC or not found:
        rows = _fetch_scrip_master_rows()
        master_count = 0
        for row in rows:
            if not _is_sensex_option_row(row):
                continue
            sym = str(row.get("tradingsymbol") or row.get("symbol") or "")
            exp = _parse_expiry(str(row.get("expiry") or "")) or _expiry_from_symbol(sym)
            if exp:
                found.add(exp.replace(hour=0, minute=0, second=0, microsecond=0))
                master_count += 1
        if master_count:
            source_parts.append("scrip_master")
            iso_list = sorted({d.strftime("%Y-%m-%d") for d in found})
            _save_disk_cache(iso_list, "+".join(source_parts) or "unknown")

    if not found and cached_dates:
        for d in cached_dates:
            parsed = _parse_expiry(str(d))
            if parsed:
                found.add(parsed.replace(hour=0, minute=0, second=0, microsecond=0))
        source_parts.append("cache_stale")

    dates = sorted(found)
    source = "+".join(dict.fromkeys(source_parts)) or "default_thursday"
    return dates, source


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _week_key(d: datetime) -> tuple[int, int]:
    iso = d.isocalendar()
    return iso.year, iso.week


def _thursday_of_week(d: datetime) -> datetime:
    """Fallback weekly expiry when market calendar unavailable."""
    days_to_thu = (3 - d.weekday()) % 7
    if d.weekday() > 3:
        days_to_thu -= 7
    return (d + timedelta(days=days_to_thu)).replace(hour=0, minute=0, second=0, microsecond=0)


@lru_cache(maxsize=1)
def _expiry_calendar() -> tuple[list[str], dict[tuple[int, int], str], str]:
    dts, source = _collect_expiry_datetimes()
    iso_dates = sorted({_iso(d) for d in dts})
    week_map: dict[tuple[int, int], str] = {}
    for d in dts:
        week_map[_week_key(d)] = _iso(d)
    return iso_dates, week_map, source


def refresh_expiry_calendar() -> None:
    _expiry_calendar.cache_clear()


def contract_expiry_for_week(date_str: str) -> str | None:
    """Contract expiry date (calendar / scrip master) for the week containing date_str."""
    try:
        dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None
    _, week_map, _ = _expiry_calendar()
    wk = _week_key(dt)
    if wk in week_map:
        return week_map[wk]
    return _iso(_thursday_of_week(dt))


def expiry_for_week(date_str: str) -> str | None:
    """Trading session date for SENSEX weekly expiry (holiday-adjusted)."""
    contract = contract_expiry_for_week(date_str)
    if not contract:
        return None
    return resolve_session_expiry_date(contract)


def is_sensex_expiry_date(date_str: str) -> bool:
    """True if date_str is the resolved SENSEX expiry session for its week."""
    exp = expiry_for_week(date_str)
    return exp is not None and date_str.strip()[:10] == exp


def next_expiry_from(today: datetime | None = None) -> datetime | None:
    now = (today or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    dates, _, _ = _expiry_calendar()
    for d in dates:
        parsed = _parse_expiry(d)
        if parsed and parsed >= now:
            return parsed
    return _thursday_of_week(now) if now.weekday() <= 3 else _thursday_of_week(now + timedelta(days=7))


def format_expiry_label(date_str: str | None) -> str:
    if not date_str:
        return "Unknown"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return date_str
    day = _WEEKDAY_NAMES[dt.weekday()]
    return f"{day}, {dt.strftime('%d %b %Y')}"


def get_expiry_info(reference_date: str | None = None) -> dict[str, Any]:
    """Public snapshot for API / dashboard."""
    ref = reference_date or datetime.now().strftime("%Y-%m-%d")
    dates, week_map, source = _expiry_calendar()
    contract_expiry = contract_expiry_for_week(ref)
    current_week_expiry = expiry_for_week(ref)
    nxt = next_expiry_from(_parse_expiry(ref) or datetime.now())
    return {
        "referenceDate": ref,
        "contractExpiryDate": contract_expiry,
        "currentWeekExpiryDate": current_week_expiry,
        "currentWeekExpiryLabel": format_expiry_label(current_week_expiry),
        "contractExpiryLabel": format_expiry_label(contract_expiry),
        "nextExpiryDate": _iso(nxt) if nxt else None,
        "nextExpiryLabel": format_expiry_label(_iso(nxt) if nxt else None),
        "knownExpiryDates": dates[-12:],
        "source": source,
        "autoDetected": bool(dates),
        "holidayAdjusted": bool(
            contract_expiry and current_week_expiry and contract_expiry != current_week_expiry
        ),
    }
