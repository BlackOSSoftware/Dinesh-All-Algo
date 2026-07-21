"""
Order execution layer for SENSEX adaptive trend — trigger audit, immediate placement,
state repair. Does not alter strategy math (process_bar / TP / SL / trail rules).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import StrategySettings, TradePosition
from app.services import trading_repository as tr
from app.services.sensex_option_buy import LEG_SOB
from app.services.sensex_trend_core import (
    Signal,
    SignalKind,
    TrendParams,
    crossed_down,
    crossed_up,
    touched_at_or_above,
    touched_at_or_below,
)

LOG = logging.getLogger(__name__)


def ts_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def enrich_bar_for_tick_cross(
    live_bar: dict[str, Any] | None,
    *,
    ltp: float,
    prev_ltp: float | None,
) -> dict[str, Any]:
    """
    Expand minute OHLC so a single-tick jump (77500→77497) is visible to process_bar
    without changing strategy rules — only the live data bridge fed into the bar.
    """
    px = float(ltp)
    bar = dict(live_bar) if live_bar else {}
    bar.setdefault("open", px)
    bar.setdefault("high", px)
    bar.setdefault("low", px)
    bar.setdefault("close", px)
    if prev_ltp is not None:
        p = float(prev_ltp)
        bar["high"] = max(float(bar.get("high") or px), px, p)
        bar["low"] = min(float(bar.get("low") or px), px, p)
        bar["prev_close"] = p
    return bar


def repair_orphan_execution_state(
    db: Session,
    user_id: int,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    """
    Fix execution desync: initial_entry_consumed / pending open_cycle without OPEN row.
    """
    pos = tr.get_open_position_by_leg(db, user_id, LEG_SOB)
    if pos is not None:
        return runtime

    changed = False
    if runtime.get("initial_entry_consumed"):
        LOG.warning(
            "S1_EXEC_REPAIR user=%s ts=%s reason=initial_entry_consumed_without_position",
            user_id,
            ts_ms(),
        )
        runtime["initial_entry_consumed"] = False
        changed = True

    if runtime.get("cycle_id") is not None or runtime.get("core_lots"):
        LOG.warning(
            "S1_EXEC_REPAIR user=%s ts=%s reason=phantom_cycle_runtime cycle_id=%s",
            user_id,
            ts_ms(),
            runtime.get("cycle_id"),
        )
        for k in (
            "cycle_id",
            "trail_extreme",
            "entry_kind",
            "entries_filled",
            "adaptive_ref",
            "core_lots",
            "avg_lots",
            "sl_level",
            "t1_level_avg",
            "t1_level_core",
            "avg_t1_done",
            "core_t1_done",
            "cycle_extreme",
        ):
            runtime.pop(k, None)
        changed = True

    pending = runtime.get("pending_signal")
    if pending and not isinstance(pending, dict):
        runtime.pop("pending_signal", None)
        changed = True

    if changed:
        tr.merge_strategy_runtime(db, user_id, runtime)
    return runtime


def audit_trigger_levels(
    *,
    user_id: int,
    mode: str,
    base: float,
    ltp: float,
    prev_ltp: float | None,
    bar: dict[str, Any],
    p: TrendParams,
    pos: TradePosition | None,
) -> None:
    """Detailed trigger audit — execution layer observability only."""
    hi = float(bar.get("high") or ltp)
    lo = float(bar.get("low") or ltp)
    prev = float(bar.get("prev_close")) if bar.get("prev_close") is not None else prev_ltp
    ce_trig = base + p.entry_trigger
    pe_trig = base - p.entry_trigger

    ce_cross = (
        prev is not None
        and p.call_enabled
        and crossed_up(prev, hi, ce_trig)
    )
    pe_cross = (
        prev is not None
        and p.put_enabled
        and crossed_down(prev, lo, pe_trig)
    )
    ce_touch = p.call_enabled and touched_at_or_above(hi, ce_trig)
    pe_touch = p.put_enabled and touched_at_or_below(lo, pe_trig)

    LOG.info(
        "S1_TRIGGER_AUDIT user=%s ts=%s mode=%s ltp=%.2f prev_ltp=%s bar[h=%.2f l=%.2f pc=%s] "
        "call_trig=%.2f put_trig=%.2f ce_cross=%s pe_cross=%s ce_touch=%s pe_touch=%s open_pos=%s",
        user_id,
        ts_ms(),
        mode,
        ltp,
        f"{float(prev_ltp):.2f}" if prev_ltp is not None else "None",
        hi,
        lo,
        f"{float(prev):.2f}" if prev is not None else "None",
        ce_trig,
        pe_trig,
        ce_cross,
        pe_cross,
        ce_touch,
        pe_touch,
        bool(pos),
    )


def store_pending_signal(runtime: dict[str, Any], sig: Signal) -> None:
    runtime["pending_signal"] = {
        "kind": sig.kind.value,
        "side": sig.side,
        "price": float(sig.price),
        "first_entry": float(sig.first_entry),
        "lots": int(sig.lots),
        "cycle_id": int(sig.cycle_id),
        "entry_kind": sig.entry_kind.value,
        "cycle_base": float(sig.cycle_base),
        "stored_at_ms": ts_ms(),
    }


def clear_pending_signal(runtime: dict[str, Any]) -> None:
    runtime.pop("pending_signal", None)


def verify_entry_open(db: Session, user_id: int, sig: Signal) -> bool:
    if sig.kind not in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE):
        return True
    pos = tr.get_open_position_by_leg(db, user_id, LEG_SOB)
    if pos is None:
        LOG.error(
            "S1_EXEC_VERIFY_FAIL user=%s ts=%s kind=%s side=%s — no OPEN row after placement",
            user_id,
            ts_ms(),
            sig.kind.value,
            sig.side,
        )
        return False
    mode = (pos.trading_mode or "PAPER").upper()
    if mode == "PAPER":
        return float(pos.entry_price or 0) > 0
    if float(pos.entry_price or 0) > 0:
        return True
    return bool(pos.order_id)


def execute_signals_immediate(
    db: Session,
    st_row: StrategySettings,
    cfg: dict[str, Any],
    p: TrendParams,
    signals: list[Signal],
    index_ltp: float,
    *,
    execute_fn,
) -> tuple[bool, dict[str, Any]]:
    """
    Place orders synchronously for each signal. Returns (all_ok, pending_runtime_patch).
    """
    uid = st_row.user_id
    mode = (st_row.trading_mode or "PAPER").upper()
    runtime_patch: dict[str, Any] = {}

    for sig in signals:
        t0 = time.perf_counter()
        pos = tr.get_open_position_by_leg(db, uid, LEG_SOB)
        LOG.info(
            "S1_ORDER_ATTEMPT user=%s ts=%s mode=%s kind=%s side=%s trigger=%.2f ltp=%.2f "
            "lots=%s cycle=%s existing_pos=%s",
            uid,
            ts_ms(),
            mode,
            sig.kind.value,
            sig.side,
            float(sig.price),
            float(index_ltp),
            sig.lots,
            sig.cycle_id,
            bool(pos),
        )

        ok = execute_fn(db, st_row, cfg, p, sig, index_ltp, pos=pos)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if not ok:
            LOG.warning(
                "S1_ORDER_REJECT user=%s ts=%s kind=%s side=%s trigger=%.2f ltp=%.2f "
                "elapsed_ms=%.2f",
                uid,
                ts_ms(),
                sig.kind.value,
                sig.side,
                float(sig.price),
                float(index_ltp),
                elapsed_ms,
            )
            store_pending_signal(runtime_patch, sig)
            return False, runtime_patch

        if not verify_entry_open(db, uid, sig):
            store_pending_signal(runtime_patch, sig)
            return False, runtime_patch

        pos_after = tr.get_open_position_by_leg(db, uid, LEG_SOB)
        LOG.info(
            "S1_ORDER_OK user=%s ts=%s kind=%s side=%s trigger=%.2f ltp=%.2f "
            "elapsed_ms=%.2f pos_id=%s status=%s lots=%s entry_px=%s",
            uid,
            ts_ms(),
            sig.kind.value,
            sig.side,
            float(sig.price),
            float(index_ltp),
            elapsed_ms,
            getattr(pos_after, "id", None),
            getattr(pos_after, "status", None),
            getattr(pos_after, "lots", None),
            getattr(pos_after, "entry_price", None),
        )
        clear_pending_signal(runtime_patch)

    return True, runtime_patch
