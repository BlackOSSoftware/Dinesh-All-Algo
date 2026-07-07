"""
Historical SENSEX BFO option instrument archive for backtesting expired contracts.

Backtests MUST resolve tokens from this archive — not from the live Angel scrip master alone.
The archive is append-only: sync merges new rows but never deletes expired entries.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT, settings
from app.services.bfo_options import ResolvedOption, _norm_side, _parse_instruments
from app.services.bfo_scrip_resolver import (
    _is_sensex_option_row,
    _parse_expiry,
    _row_expiry_iso,
    _row_side,
    _row_strike,
    _row_symbol,
    build_sensex_weekly_symbol,
    decode_weekly_symbol_expiry,
)

LOG = logging.getLogger(__name__)

_DB_PATH = BACKEND_ROOT / "instance" / "sensex_historical_instruments.db"
_LEGACY_JSON = BACKEND_ROOT / "instance" / "bfo_token_archive.json"
_SCRIP_CACHE = BACKEND_ROOT / "instance" / "bfo_scrip_cache.json"
_IMPORT_JSON = BACKEND_ROOT / "instance" / "sensex_historical_import.json"

_SCRIP_MASTER_URLS = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
)


@dataclass(frozen=True)
class ArchivedInstrument:
    exchange: str
    trading_symbol: str
    instrument_token: str
    expiry_date: str
    strike: float
    option_type: str
    lot_size: int
    start_date: str | None
    end_date: str | None
    historical_availability: bool
    source: str

    def to_resolved_option(self) -> ResolvedOption:
        return ResolvedOption(
            strike=self.strike,
            side=self.option_type,
            token=self.instrument_token,
            tradingsymbol=self.trading_symbol,
            lotsize=self.lot_size,
            expiry_date=self.expiry_date,
        )


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sensex_instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL DEFAULT 'BFO',
            trading_symbol TEXT NOT NULL UNIQUE,
            instrument_token TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            lot_size INTEGER NOT NULL DEFAULT 20,
            start_date TEXT,
            end_date TEXT,
            historical_availability INTEGER NOT NULL DEFAULT 1,
            source TEXT,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sensex_expiry_strike_side
            ON sensex_instruments(expiry_date, strike, option_type);
        CREATE INDEX IF NOT EXISTS idx_sensex_token ON sensex_instruments(instrument_token);
        """
    )
    return conn


def _row_to_archived(row: sqlite3.Row) -> ArchivedInstrument:
    return ArchivedInstrument(
        exchange=str(row["exchange"]),
        trading_symbol=str(row["trading_symbol"]),
        instrument_token=str(row["instrument_token"]),
        expiry_date=str(row["expiry_date"]),
        strike=float(row["strike"]),
        option_type=str(row["option_type"]),
        lot_size=int(row["lot_size"]),
        start_date=str(row["start_date"]) if row["start_date"] else None,
        end_date=str(row["end_date"]) if row["end_date"] else None,
        historical_availability=bool(row["historical_availability"]),
        source=str(row["source"] or ""),
    )


def _listing_start(expiry_date: str) -> str:
    try:
        exp = datetime.strptime(expiry_date[:10], "%Y-%m-%d")
        start = exp - timedelta(days=90)
        return start.strftime("%Y-%m-%d")
    except ValueError:
        return expiry_date[:10]


def upsert_instrument(
    *,
    exchange: str,
    trading_symbol: str,
    instrument_token: str,
    expiry_date: str,
    strike: float,
    option_type: str,
    lot_size: int = 20,
    start_date: str | None = None,
    end_date: str | None = None,
    historical_availability: bool = True,
    source: str = "unknown",
) -> None:
    sym = trading_symbol.strip().upper()
    token = str(instrument_token).strip()
    if not sym or not token:
        return
    exp = expiry_date[:10]
    side = _norm_side(option_type)
    end = (end_date or exp)[:10]
    start = (start_date or _listing_start(exp))[:10]
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sensex_instruments (
                exchange, trading_symbol, instrument_token, expiry_date, strike, option_type,
                lot_size, start_date, end_date, historical_availability, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trading_symbol) DO UPDATE SET
                instrument_token=excluded.instrument_token,
                expiry_date=excluded.expiry_date,
                strike=excluded.strike,
                option_type=excluded.option_type,
                lot_size=excluded.lot_size,
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                historical_availability=excluded.historical_availability,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (
                exchange.upper(), sym, token, exp, float(strike), side,
                max(1, int(lot_size)), start, end, 1 if historical_availability else 0, source, now,
            ),
        )
        conn.commit()


def upsert_from_master_row(row: dict[str, Any], *, source: str = "scrip_master") -> None:
    if not _is_sensex_option_row(row):
        return
    sym = _row_symbol(row)
    token = str(row.get("token") or row.get("symboltoken") or "").strip()
    if not sym or not token:
        return
    strike = _row_strike(row)
    side = _row_side(row)
    exp = _row_expiry_iso(row) or decode_weekly_symbol_expiry(sym)
    if not exp or strike <= 0 or side not in ("CE", "PE"):
        return
    try:
        lot = int(row.get("lotsize") or row.get("lotSize") or settings.default_sensex_option_lot_size or 20)
    except (TypeError, ValueError):
        lot = 20
    upsert_instrument(
        exchange=str(row.get("exch_seg") or "BFO"),
        trading_symbol=sym,
        instrument_token=token,
        expiry_date=exp,
        strike=strike,
        option_type=side,
        lot_size=lot,
        source=source,
    )


def _load_json_archive(path: Path, source: str) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    count = 0
    symbols = data.get("symbols") if isinstance(data, dict) else None
    if isinstance(symbols, dict):
        for sym, hit in symbols.items():
            if not isinstance(hit, dict):
                continue
            token = str(hit.get("token") or "").strip()
            if not token:
                continue
            upsert_instrument(
                exchange="BFO",
                trading_symbol=str(hit.get("symbol") or sym),
                instrument_token=token,
                expiry_date=str(hit.get("expiry") or decode_weekly_symbol_expiry(sym) or "")[:10],
                strike=float(hit.get("strike") or 0),
                option_type=str(hit.get("side") or "CE"),
                lot_size=int(hit.get("lotsize") or 20),
                source=source,
            )
            count += 1
    elif isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                upsert_from_master_row(row, source=source)
                count += 1
    return count


def _fetch_master_rows() -> list[dict[str, Any]]:
    if _SCRIP_CACHE.is_file():
        try:
            cached = json.loads(_SCRIP_CACHE.read_text(encoding="utf-8"))
            rows = cached.get("rows") if isinstance(cached, dict) else None
            if isinstance(rows, list) and rows:
                return [r for r in rows if isinstance(r, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    ctx = ssl.create_default_context()
    for url in _SCRIP_MASTER_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "strategy-3/1.0"})
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict) and _is_sensex_option_row(r)]
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError) as exc:
            LOG.warning("Archive sync master fetch failed %s: %s", url, exc)
    return []


def sync_archive(*, fetch_master: bool = True) -> dict[str, int]:
    """Merge legacy JSON, env instruments, and optional live master into SQLite archive."""
    stats = {"legacy_json": 0, "import_json": 0, "env_json": 0, "master": 0, "total": 0}
    stats["legacy_json"] = _load_json_archive(_LEGACY_JSON, "legacy_json")
    stats["import_json"] = _load_json_archive(_IMPORT_JSON, "manual_import")
    for row in _parse_instruments():
        sym = str(row.get("tradingsymbol") or row.get("symbol") or "").strip()
        token = str(row.get("token") or row.get("symboltoken") or "").strip()
        if sym and token:
            upsert_instrument(
                exchange="BFO",
                trading_symbol=sym,
                instrument_token=token,
                expiry_date=str(row.get("expiry") or row.get("expiryDate") or decode_weekly_symbol_expiry(sym) or "")[:10],
                strike=float(row.get("strike") or row.get("strikeprice") or 0),
                option_type=str(row.get("side") or row.get("optiontype") or "CE"),
                lot_size=int(row.get("lotsize") or row.get("lotSize") or 20),
                source="env_json",
            )
            stats["env_json"] += 1
    if fetch_master:
        rows = _fetch_master_rows()
        for row in rows:
            upsert_from_master_row(row, source="scrip_master")
        stats["master"] = len(rows)
    with _connect() as conn:
        stats["total"] = conn.execute("SELECT COUNT(*) FROM sensex_instruments").fetchone()[0]
    LOG.info("SENSEX instrument archive synced: %s", stats)
    return stats


def archive_stats() -> dict[str, Any]:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM sensex_instruments").fetchone()[0]
        expiries = [
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT expiry_date FROM sensex_instruments ORDER BY expiry_date DESC LIMIT 20"
            ).fetchall()
        ]
    return {"total": total, "recentExpiries": expiries, "dbPath": str(_DB_PATH)}


def _lookup_symbol(symbol: str) -> ArchivedInstrument | None:
    sym = symbol.strip().upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sensex_instruments WHERE trading_symbol = ? AND historical_availability = 1",
            (sym,),
        ).fetchone()
    return _row_to_archived(row) if row else None


def _lookup_expiry_strike_side(expiry_date: str, strike: float, option_type: str) -> ArchivedInstrument | None:
    exp = expiry_date[:10]
    side = _norm_side(option_type)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM sensex_instruments
            WHERE expiry_date = ? AND option_type = ? AND ABS(strike - ?) < 0.01
              AND historical_availability = 1
            ORDER BY updated_at DESC LIMIT 1
            """,
            (exp, side, float(strike)),
        ).fetchone()
    return _row_to_archived(row) if row else None


def resolve_historical_sensex_option(
    strike: float,
    side: str,
    *,
    expiry_date: str,
    trade_date: str | None = None,
) -> ArchivedInstrument | None:
    """
    Resolve token from historical archive ONLY (for backtest).
    Never falls back to live scrip master.
    """
    exp = expiry_date.strip()[:10]
    want = _norm_side(side)
    expected = build_sensex_weekly_symbol(strike, want, exp)

    hit = _lookup_symbol(expected)
    if hit and hit.expiry_date[:10] == exp:
        if trade_date and trade_date[:10] > exp:
            return None
        return hit

    hit = _lookup_expiry_strike_side(exp, strike, want)
    if hit:
        if trade_date and trade_date[:10] > exp:
            return None
        return hit

    return None


def resolve_historical_or_none_resolved(
    strike: float,
    side: str,
    *,
    expiry_date: str,
    trade_date: str | None = None,
) -> ResolvedOption | None:
    hit = resolve_historical_sensex_option(strike, side, expiry_date=expiry_date, trade_date=trade_date)
    return hit.to_resolved_option() if hit else None
