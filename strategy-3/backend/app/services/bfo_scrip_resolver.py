"""Resolve BFO SENSEX option contracts — weekly symbol build, exact expiry, token archive."""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from app.config import BACKEND_ROOT, settings
from app.services.bfo_options import ResolvedOption, _norm_side, resolve_bfo_option

LOG = logging.getLogger(__name__)

_CACHE_PATH = BACKEND_ROOT / "instance" / "bfo_scrip_cache.json"
_ARCHIVE_PATH = BACKEND_ROOT / "instance" / "bfo_token_archive.json"
_CACHE_TTL_SEC = 6 * 3600

_SCRIP_MASTER_URLS = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
)

# SENSEX2662577100CE → yy=26, month=6, day=25, strike=77100, side=CE
_WEEKLY_SYMBOL_RE = re.compile(r"^SENSEX(\d{2})([1-9])(\d{2})(\d{4,6})(CE|PE)$", re.IGNORECASE)


def build_sensex_weekly_symbol(strike: float, side: str, expiry_date: str) -> str:
    """Angel weekly format: SENSEX{YY}{M}{DD}{STRIKE}{CE|PE} e.g. SENSEX2662577100CE."""
    dt = datetime.strptime(expiry_date.strip()[:10], "%Y-%m-%d")
    yy = dt.year % 100
    return f"SENSEX{yy}{dt.month}{dt.day:02d}{int(strike)}{_norm_side(side)}"


def decode_weekly_symbol_expiry(symbol: str) -> str | None:
    """Decode weekly symbol to YYYY-MM-DD, or None if not weekly format."""
    m = _WEEKLY_SYMBOL_RE.match((symbol or "").strip().upper())
    if not m:
        return None
    yy, month, day, _, _ = m.groups()
    try:
        dt = datetime(2000 + int(yy), int(month), int(day))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


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
    decoded = decode_weekly_symbol_expiry(symbol)
    if decoded:
        return datetime.strptime(decoded, "%Y-%m-%d")
    m = re.search(r"(\d{1,2}[A-Z]{3}\d{2,4})", (symbol or "").upper())
    if not m:
        return None
    return _parse_expiry(m.group(1))


def _is_sensex_option_row(row: dict[str, Any]) -> bool:
    exch = str(row.get("exch_seg") or row.get("exchange") or "").upper()
    if exch and "BFO" not in exch:
        return False
    name = str(row.get("name") or row.get("symbolname") or "").upper()
    sym = str(row.get("symbol") or row.get("tradingsymbol") or "").upper()
    if name == "SENSEX":
        return True
    if sym.startswith("SENSEX") and not sym.startswith("SENSEX50"):
        return True
    return False


def _normalize_strike(raw: float) -> float:
    if raw <= 0:
        return 0.0
    if raw >= 100_000:
        return raw / 100.0
    return raw


def _strike_from_symbol(symbol: str) -> float:
    sym = (symbol or "").upper()
    m = _WEEKLY_SYMBOL_RE.match(sym)
    if m:
        try:
            return float(m.group(4))
        except ValueError:
            pass
    m = re.search(r"(\d{4,6})(?:CE|PE)$", sym)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.0


def _row_strike(row: dict[str, Any]) -> float:
    sym = _row_symbol(row)
    from_sym = _strike_from_symbol(sym)
    if from_sym > 0:
        return from_sym
    for key in ("strike", "strikeprice", "strike_price"):
        try:
            v = _normalize_strike(float(row.get(key) or 0))
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return 0.0


def _row_side(row: dict[str, Any]) -> str:
    sym = str(row.get("symbol") or row.get("tradingsymbol") or "").upper()
    if sym.endswith("CE"):
        return "CE"
    if sym.endswith("PE"):
        return "PE"
    return _norm_side(str(row.get("optiontype") or row.get("side") or ""))


def _row_symbol(row: dict[str, Any]) -> str:
    return str(row.get("tradingsymbol") or row.get("symbol") or "").strip()


def _row_expiry_iso(row: dict[str, Any]) -> str | None:
    sym = _row_symbol(row)
    decoded = decode_weekly_symbol_expiry(sym)
    if decoded:
        return decoded
    exp = _parse_expiry(str(row.get("expiry") or "")) or _expiry_from_symbol(sym)
    return exp.strftime("%Y-%m-%d") if exp else None


def _load_token_archive() -> dict[str, dict[str, Any]]:
    if not _ARCHIVE_PATH.is_file():
        return {}
    try:
        data = json.loads(_ARCHIVE_PATH.read_text(encoding="utf-8"))
        rows = data.get("symbols") if isinstance(data, dict) else None
        return rows if isinstance(rows, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_token_archive(symbols: dict[str, dict[str, Any]]) -> None:
    _ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ARCHIVE_PATH.write_text(
        json.dumps({"_ts": time.time(), "symbols": symbols}, indent=0),
        encoding="utf-8",
    )


def _archive_row(row: dict[str, Any], archive: dict[str, dict[str, Any]]) -> None:
    sym = _row_symbol(row).upper()
    if not sym:
        return
    token = str(row.get("token") or row.get("symboltoken") or "").strip()
    if not token:
        return
    archive[sym] = {
        "token": token,
        "symbol": sym,
        "strike": _row_strike(row),
        "side": _row_side(row),
        "expiry": _row_expiry_iso(row),
        "lotsize": int(row.get("lotsize") or row.get("lotSize") or settings.default_sensex_option_lot_size or 20),
    }


def _merge_rows_into_archive(rows: list[dict[str, Any]]) -> None:
    archive = _load_token_archive()
    before = len(archive)
    for row in rows:
        if _is_sensex_option_row(row):
            _archive_row(row, archive)
    if len(archive) > before:
        _save_token_archive(archive)


def _load_master_rows() -> list[dict[str, Any]]:
    cached = _read_disk_cache()
    if cached:
        _merge_rows_into_archive(cached)
        return cached
    ctx = ssl.create_default_context()
    for url in _SCRIP_MASTER_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "strategy-3/1.0"})
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(data, list):
                rows = [r for r in data if isinstance(r, dict) and _is_sensex_option_row(r)]
                LOG.info("BFO scrip master: %d SENSEX option rows (from %d total)", len(rows), len(data))
                _write_disk_cache(rows)
                _merge_rows_into_archive(rows)
                return rows
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError) as exc:
            LOG.warning("BFO scrip master fetch failed %s: %s", url, exc)
    return []


def _read_disk_cache() -> list[dict[str, Any]] | None:
    if not _CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if time.time() - float(data.get("_ts") or 0) > _CACHE_TTL_SEC:
            return None
        rows = data.get("rows")
        return rows if isinstance(rows, list) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_disk_cache(rows: list[dict[str, Any]]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps({"_ts": time.time(), "rows": rows}, indent=0), encoding="utf-8")


def _row_to_option(row: dict[str, Any], strike: float, side: str, expiry_date: str | None) -> ResolvedOption | None:
    token = str(row.get("token") or row.get("symboltoken") or "").strip()
    sym = _row_symbol(row)
    if not token or not sym:
        return None
    try:
        lot = int(row.get("lotsize") or row.get("lotSize") or settings.default_sensex_option_lot_size or 20)
    except (TypeError, ValueError):
        lot = 20
    sk = _row_strike(row) or float(strike)
    exp = _row_expiry_iso(row) or expiry_date
    return ResolvedOption(
        strike=sk,
        side=_norm_side(side),
        token=token,
        tradingsymbol=sym,
        lotsize=max(1, lot),
        expiry_date=exp,
    )


def _lookup_by_symbol(expected_symbol: str) -> ResolvedOption | None:
    sym_key = expected_symbol.strip().upper()
    archive = _load_token_archive()
    if sym_key in archive:
        hit = archive[sym_key]
        return ResolvedOption(
            strike=float(hit.get("strike") or 0),
            side=_norm_side(str(hit.get("side") or "")),
            token=str(hit.get("token") or ""),
            tradingsymbol=sym_key,
            lotsize=max(1, int(hit.get("lotsize") or 20)),
            expiry_date=str(hit.get("expiry") or "")[:10] or None,
        )
    for row in _load_master_rows():
        if _row_symbol(row).upper() == sym_key:
            opt = _row_to_option(row, _row_strike(row), _row_side(row), decode_weekly_symbol_expiry(sym_key))
            if opt:
                return opt
    return None


def resolve_from_scrip_master(
    strike: float,
    side: str,
    *,
    expiry_date: str | None = None,
) -> ResolvedOption | None:
    """Exact expiry match only — builds weekly symbol and looks up by symbol + expiry."""
    if not expiry_date:
        return None

    want = _norm_side(side)
    target = expiry_date.strip()[:10]
    expected = build_sensex_weekly_symbol(strike, want, target)

    hit = _lookup_by_symbol(expected)
    if hit:
        sym_exp = decode_weekly_symbol_expiry(hit.tradingsymbol) or hit.expiry_date
        if sym_exp and sym_exp != target:
            LOG.warning("Symbol %s expiry %s != session %s", hit.tradingsymbol, sym_exp, target)
            return None
        LOG.info("Resolved BFO %s strike %.0f expiry %s → %s (%s)", want, strike, target, hit.tradingsymbol, hit.token)
        return ResolvedOption(
            strike=float(strike),
            side=want,
            token=hit.token,
            tradingsymbol=hit.tradingsymbol,
            lotsize=hit.lotsize,
            expiry_date=target,
        )

    # Fallback: scan master for exact expiry + strike + side (monthly symbols)
    for row in _load_master_rows():
        if _row_side(row) != want:
            continue
        if abs(_row_strike(row) - float(strike)) > 0.01:
            continue
        row_exp = _row_expiry_iso(row)
        if row_exp != target:
            continue
        opt = _row_to_option(row, strike, want, target)
        if opt:
            LOG.info("Resolved BFO %s strike %.0f expiry %s → %s (%s)", want, strike, target, opt.tradingsymbol, opt.token)
            return opt

    return None


def resolve_sensex_option(
    strike: float,
    side: str,
    *,
    expiry_date: str | None = None,
) -> ResolvedOption | None:
    """JSON config first, then exact weekly symbol / expiry match in scrip master + archive."""
    hit = resolve_bfo_option(strike, side, expiry_date=expiry_date)
    if hit:
        if expiry_date and hit.expiry_date and hit.expiry_date[:10] != expiry_date[:10]:
            hit = None
        elif hit:
            return hit
    return resolve_from_scrip_master(strike, side, expiry_date=expiry_date)
