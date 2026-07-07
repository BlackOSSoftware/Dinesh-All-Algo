"""
Resolve BFO Sensex option contract from strike/side using ANGEL_BFO_INSTRUMENTS_JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import settings

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedOption:
    strike: float
    side: str  # PE | CE
    token: str
    tradingsymbol: str
    lotsize: int
    expiry_date: str | None = None


def _parse_instruments() -> list[dict[str, Any]]:
    raw = (settings.angel_bfo_instruments_json or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        LOG.warning("ANGEL_BFO_INSTRUMENTS_JSON invalid JSON: %s", e)
        return []
    if isinstance(data, dict) and isinstance(data.get("instruments"), list):
        data = data["instruments"]
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, dict):
            out.append(row)
    return out


def _norm_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s in ("PUT", "PE"):
        return "PE"
    if s in ("CALL", "CE"):
        return "CE"
    return s


def resolve_bfo_option(strike: float, side: str, *, expiry_date: str | None = None) -> ResolvedOption | None:
    """
    Pick instrument row matching side (PE/CE), closest strike, optional expiry date.
    Rows must include: strike (number), side (PE/CE), token, tradingsymbol, lotsize.
    """
    want = _norm_side(side)
    rows = _parse_instruments()
    if not rows:
        return None
    best: tuple[float, float, dict[str, Any]] | None = None
    for row in rows:
        rs = _norm_side(str(row.get("side") or row.get("optiontype") or ""))
        if rs != want:
            continue
        try:
            sk = float(row.get("strike") or row.get("strikeprice") or 0)
        except (TypeError, ValueError):
            continue
        if sk <= 0:
            continue
        row_exp = str(row.get("expiry") or row.get("expiryDate") or row.get("expiry_date") or "")[:10]
        if expiry_date and row_exp and row_exp != expiry_date[:10]:
            continue
        strike_dist = abs(sk - float(strike))
        exp_dist = 0.0 if (not expiry_date or not row_exp or row_exp == expiry_date[:10]) else 999999.0
        if best is None or (exp_dist, strike_dist) < (best[0], best[1]):
            best = (exp_dist, strike_dist, row)
    if best is None:
        return None
    row = best[2]
    token = str(row.get("token") or row.get("symboltoken") or "").strip()
    sym = str(row.get("tradingsymbol") or row.get("symbol") or "").strip()
    if not token or not sym:
        return None
    try:
        lot = int(row.get("lotsize") or row.get("lotSize") or 1)
    except (TypeError, ValueError):
        lot = 1
    try:
        sk = float(row.get("strike") or strike)
    except (TypeError, ValueError):
        sk = float(strike)
    exp = str(row.get("expiry") or row.get("expiryDate") or expiry_date or "")[:10] or None
    return ResolvedOption(strike=sk, side=want, token=token, tradingsymbol=sym, lotsize=max(1, lot), expiry_date=exp)
