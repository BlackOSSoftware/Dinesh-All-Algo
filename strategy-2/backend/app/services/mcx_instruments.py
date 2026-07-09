"""MCX commodity instrument definitions (Crude Oil, Natural Gas, Silver Micro)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.services.mcx_scrip_resolver import resolve_mcx_instrument, resolve_mcx_instrument_for_expiry

LOG = logging.getLogger(__name__)

DEFAULT_INSTRUMENTS: list[dict[str, Any]] = [
    {
        "key": "CRUDE_OIL",
        "label": "Crude Oil",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 10,
    },
    {
        "key": "CRUDE_OIL_MINI",
        "label": "Crude Oil Mini",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 10,
    },
    {
        "key": "CRUDE_OIL_MEGA",
        "label": "Crude Oil Mega",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 100,
    },
    {
        "key": "NATURAL_GAS",
        "label": "Natural Gas",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 1250,
    },
    {
        "key": "NATURAL_GAS_MINI",
        "label": "Natural Gas Mini",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 250,
    },
    {
        "key": "NATURAL_GAS_MEGA",
        "label": "Natural Gas Mega",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 1250,
    },
    {
        "key": "SILVER_MICRO",
        "label": "Silver Micro",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 1,
    },
    {
        "key": "SILVER_MINI",
        "label": "Silver Mini",
        "exchange": "MCX",
        "token": "",
        "tradingsymbol": "",
        "lotsize": 5,
    },
]


@dataclass(frozen=True)
class McxInstrument:
    key: str
    label: str
    exchange: str
    token: str
    tradingsymbol: str
    lotsize: int

    @property
    def configured(self) -> bool:
        return bool(self.token.strip() and self.tradingsymbol.strip())


def _parse_instruments_raw(raw: str) -> list[dict[str, Any]]:
    if not (raw or "").strip():
        return DEFAULT_INSTRUMENTS
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        LOG.warning("Invalid ANGEL_MCX_INSTRUMENTS_JSON — using defaults")
        return DEFAULT_INSTRUMENTS
    if not isinstance(data, list):
        return DEFAULT_INSTRUMENTS
    return data


def load_mcx_instruments() -> dict[str, McxInstrument]:
    out: dict[str, McxInstrument] = {}
    for row in _parse_instruments_raw(settings.angel_mcx_instruments_json):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().upper()
        if not key:
            continue
        out[key] = McxInstrument(
            key=key,
            label=str(row.get("label") or key.replace("_", " ").title()),
            exchange=str(row.get("exchange") or "MCX").upper(),
            token=str(row.get("token") or "").strip(),
            tradingsymbol=str(row.get("tradingsymbol") or "").strip(),
            lotsize=max(1, int(row.get("lotsize") or 1)),
        )
    for d in DEFAULT_INSTRUMENTS:
        key = str(d["key"]).upper()
        if key not in out:
            out[key] = McxInstrument(
                key=key,
                label=str(d["label"]),
                exchange=str(d["exchange"]),
                token=str(d.get("token") or ""),
                tradingsymbol=str(d.get("tradingsymbol") or ""),
                lotsize=int(d.get("lotsize") or 1),
            )

    for key, inst in list(out.items()):
        if inst.configured:
            continue
        resolved = resolve_mcx_instrument(key)
        if not resolved:
            continue
        out[key] = McxInstrument(
            key=key,
            label=resolved.get("label") or inst.label,
            exchange=resolved.get("exchange") or "MCX",
            token=str(resolved.get("token") or ""),
            tradingsymbol=str(resolved.get("tradingsymbol") or ""),
            lotsize=max(1, int(resolved.get("lotsize") or inst.lotsize)),
        )
    return out


def get_instrument(key: str | None, *, expiry_iso: str | None = None) -> McxInstrument | None:
    k = (key or "").strip().upper()
    if not k:
        return None
    expiry = (expiry_iso or "").strip()[:10]
    if expiry:
        resolved = resolve_mcx_instrument_for_expiry(k, expiry)
        if resolved:
            return McxInstrument(
                key=k,
                label=str(resolved.get("label") or k.replace("_", " ").title()),
                exchange=str(resolved.get("exchange") or "MCX"),
                token=str(resolved.get("token") or ""),
                tradingsymbol=str(resolved.get("tradingsymbol") or ""),
                lotsize=max(1, int(resolved.get("lotsize") or 1)),
            )
    return load_mcx_instruments().get(k)
