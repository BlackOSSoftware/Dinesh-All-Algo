"""
Backtest runner — uses sensex_trend_core (same logic as live).
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, time as dt_time
from typing import Any

from app.services.sensex_trend_core import (
    BarSlice,
    EngineState,
    EntryKind,
    SignalKind,
    TrendParams,
    cycle_sl,
    cycle_sl_for_open,
    lots_for_entry,
    points_pnl,
    process_bar,
)


def _parse_hhmm(s: str) -> dt_time | None:
    raw = (s or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", raw)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mm <= 59):
        return None
    return dt_time(h, mm)


def _bar_time_minutes(time_str: str) -> int | None:
    t = _parse_hhmm(time_str.replace("T", " ").split(" ")[-1][:5])
    if t is None:
        return None
    return t.hour * 60 + t.minute


def _in_window(time_str: str, start: str, end: str) -> bool:
    bm = _bar_time_minutes(time_str)
    st = _parse_hhmm(start) or dt_time(9, 15)
    et = _parse_hhmm(end) or dt_time(15, 30)
    if bm is None:
        return True
    sm = st.hour * 60 + st.minute
    em = et.hour * 60 + et.minute
    if sm <= em:
        return sm <= bm <= em
    return bm >= sm or bm <= em


def _at_or_after(time_str: str, hhmm: str) -> bool:
    bm = _bar_time_minutes(time_str)
    t = _parse_hhmm(hhmm)
    if bm is None or t is None:
        return False
    tm = t.hour * 60 + t.minute
    return bm >= tm


def _short_time(time_str: str) -> str:
    s = time_str.replace("T", " ")
    return s[11:16] if len(s) >= 16 else s[:5]


def _find_base_close(candles: list[dict[str, Any]], start_time: str) -> float | None:
    st = _parse_hhmm(start_time) or dt_time(9, 15)
    target = f"{st.hour:02d}:{st.minute:02d}"
    for c in candles:
        tnorm = c.get("time", "").replace("T", " ")
        if target in tnorm:
            close = c.get("close")
            if close is not None:
                return float(close)
    if candles:
        return float(candles[0].get("close") or 0)
    return None


def _planned_levels(base: float, p: TrendParams) -> list[dict[str, Any]]:
    """Planned strategy levels for the day (index-based averaging strategy)."""
    ce = round(base + p.entry_trigger, 2)
    pe = round(base - p.entry_trigger, 2)
    call_sl = round(ce - p.stop_distance, 2)
    put_sl = round(pe + p.stop_distance, 2)
    rows: list[dict[str, Any]] = [
        {
            "type": "BASE",
            "side": "—",
            "level": round(base, 2),
            "lots": 0,
            "tp1": None,
            "tp2_trail": None,
            "stop_loss": None,
            "note": "09:15 reference close",
        },
        {
            "type": "CALL_TRIGGER",
            "side": "CALL",
            "level": ce,
            "lots": lots_for_entry(p, 0),
            "tp1": round(ce + p.tp1_pts_initial, 2),
            "tp1_avg": round(ce + p.tp1_pts, 2),
            "tp2_trail": p.tp2_trail,
            "stop_loss": call_sl,
            "note": f"First entry when index crosses {ce} · core TP1 +{p.tp1_pts_initial:g}pt",
        },
        {
            "type": "PUT_TRIGGER",
            "side": "PUT",
            "level": pe,
            "lots": lots_for_entry(p, 0),
            "tp1": round(pe - p.tp1_pts_initial, 2),
            "tp1_avg": round(pe - p.tp1_pts, 2),
            "tp2_trail": p.tp2_trail,
            "stop_loss": put_sl,
            "note": f"First entry when index crosses {pe}",
        },
    ]
    for i in range(1, p.max_entries):
        avg_call = round(ce - p.averaging_gap * i, 2)
        avg_put = round(pe + p.averaging_gap * i, 2)
        if avg_call > call_sl:
            rows.append(
                {
                    "type": f"CALL_AVG_{i}",
                    "side": "CALL",
                    "level": avg_call,
                    "lots": lots_for_entry(p, i),
                    "tp1": round(ce + p.tp1_pts, 2),
                    "tp1_avg": round(ce + p.tp1_pts, 2),
                    "tp2_trail": None,
                    "stop_loss": call_sl,
                    "note": f"Averaging entry #{i + 1} (TP1 only @ +{p.tp1_pts:g}pt)",
                }
            )
        if avg_put < put_sl:
            rows.append(
                {
                    "type": f"PUT_AVG_{i}",
                    "side": "PUT",
                    "level": avg_put,
                    "lots": lots_for_entry(p, i),
                    "tp1": round(pe - p.tp1_pts, 2),
                    "tp2_trail": None,
                    "stop_loss": put_sl,
                    "note": f"Averaging entry #{i + 1} (TP1 only)",
                }
            )
    if p.re_entry_enabled:
        rows.append(
            {
                "type": "REENTRY_RULE",
                "side": "BOTH",
                "level": p.re_entry_gap,
                "lots": lots_for_entry(p, 0),
                "tp1": None,
                "tp2_trail": None,
                "stop_loss": None,
                "note": f"After TP2 trail exit, re-enter on ADP high/low ± {p.re_entry_gap:g}pt pullback (above cycle SL)",
            }
        )
    return rows


def _strike_label(strike: float, side: str) -> str:
    suffix = "PE" if (side or "").upper() == "PUT" else "CE"
    return f"{round(strike):g} {suffix}"


def _strike_detail(
    *,
    entry_kind: EntryKind,
    side: str,
    base_price: float,
    trigger_price: float,
    index_price: float,
    strike: float,
    strike_offset: float,
    avg_level: int | None,
) -> str:
    if entry_kind == EntryKind.AVERAGE:
        return (
            f"Current Index: {index_price:g}\n"
            f"Nearest Strike: {_strike_label(strike, side)}"
            + (f"\nAverage Level: AVG{avg_level}" if avg_level else "")
        )
    offset_sign = "-" if (side or "").upper() == "PUT" else "+"
    round_rule = "Round down to 100" if (side or "").upper() == "PUT" else "Round up to 100"
    if entry_kind == EntryKind.REENTRY:
        return (
            f"Re-entry Price: {trigger_price:g}\n"
            f"Strike Offset: {offset_sign}{strike_offset:g}\n"
            f"Strike Rule: {round_rule}\n"
            f"Selected Strike: {_strike_label(strike, side)}"
        )
    return (
        f"Base Price: {base_price:g}\n"
        f"Trigger Price: {trigger_price:g}\n"
        f"Strike Offset: {offset_sign}{strike_offset:g}\n"
        f"Strike Rule: {round_rule}\n"
        f"Selected Strike: {_strike_label(strike, side)}"
    )


def _timeline_from_log(
    log: list[dict[str, Any]],
    *,
    base: float,
    call_trig: float,
    put_trig: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {
            "time": "09:15",
            "event": "BASE_CAPTURED",
            "label": "Base captured",
            "side": "—",
            "price": base,
            "detail": f"Day base = {base} · Call trigger {call_trig} · Put trigger {put_trig}",
        }
    ]
    for row in log:
        action = str(row.get("action") or "").upper()
        action_lbl = str(row.get("action_label") or action)
        side = str(row.get("side") or "")
        entry_type = str(row.get("entry_type") or "")
        price = row.get("index_price")
        t = str(row.get("time") or "")
        strike_txt = str(row.get("selected_strike_label") or _strike_label(float(row.get("strike") or 0), side))

        if action in ("BUY", "AVERAGE"):
            kind = (
                "INITIAL_ENTRY"
                if entry_type == "INITIAL"
                else "REENTRY"
                if entry_type == "REENTRY"
                else "AVERAGE_ENTRY"
            )
            if entry_type == "AVERAGE":
                detail = "\n".join(
                    p
                    for p in [
                        row.get("strike_detail") or f"Current Index: {price}\nNearest Strike: {strike_txt}",
                        f"Lots Added: {row.get('lots_added', row.get('lots'))}",
                        f"Total Lots: {row.get('total_lots')}",
                    ]
                    if p
                )
            else:
                detail = "\n".join(
                    p
                    for p in [
                        row.get("strike_detail") or "",
                        f"Lots: {row.get('lots')}",
                        f"TP1: {row.get('tp1')}" if row.get("tp1") is not None else "",
                        f"SL: {row.get('stop_loss')}" if row.get("stop_loss") is not None else "",
                    ]
                    if p
                )
            out.append(
                {
                    "time": t,
                    "event": kind,
                    "label": f"{action_lbl} · {side}",
                    "side": side,
                    "price": price,
                    "detail": detail,
                }
            )
        elif action == "TP1_PARTIAL":
            detail = "\n".join(
                p
                for p in [
                    f"Exit Lots: {row.get('exit_lots', row.get('lots'))}",
                    f"Remaining Lots: {row.get('remaining_lots', row.get('total_lots'))}",
                    f"Selected Strike: {strike_txt}",
                    f"P&L: {row.get('trade_pnl')}",
                ]
                if p is not None
            )
            out.append(
                {
                    "time": t,
                    "event": "TP1_PARTIAL",
                    "label": f"{action_lbl} · {side}",
                    "side": side,
                    "price": row.get("exit_price") or price,
                    "detail": detail,
                }
            )
        elif action == "EXIT":
            reason = str(row.get("exit_reason") or "")
            if reason == "TP2_TRAIL":
                ah = row.get("adaptive_high")
                al = row.get("adaptive_low")
                detail = "\n".join(
                    p
                    for p in [
                        f"Adaptive High: {ah}" if ah is not None and side == "CALL" else None,
                        f"Adaptive Low: {al}" if al is not None and side == "PUT" else None,
                        f"Trail Distance: {row.get('tp2_trail')}",
                        f"Exit Price: {row.get('exit_price')}",
                        f"Selected Strike: {strike_txt}",
                        f"Remaining Lots: {row.get('remaining_lots', 0)}",
                        f"P&L: {row.get('trade_pnl')}",
                    ]
                    if p is not None
                )
            else:
                detail = "\n".join(
                    p
                    for p in [
                        f"Exit Price: {row.get('exit_price')}",
                        f"Selected Strike: {strike_txt}",
                        f"Exit Reason: {reason or 'closed'}",
                        f"P&L: {row.get('trade_pnl')}",
                        f"Running P&L: {row.get('running_pnl')}",
                    ]
                    if p is not None
                )
            out.append(
                {
                    "time": t,
                    "event": reason or "EXIT",
                    "label": f"{action_lbl} · {side}",
                    "side": side,
                    "price": row.get("exit_price") or price,
                    "detail": detail,
                }
            )
    return out


def _log_labels(sig_kind: SignalKind, entry_kind: EntryKind, exit_reason: str, avg_index: int) -> tuple[str, str]:
    if sig_kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE):
        if entry_kind == EntryKind.REENTRY:
            return "BUY REENTRY", "Pullback Gap"
        if sig_kind == SignalKind.OPEN_AVERAGE:
            return f"BUY AVG{avg_index}", "Averaging Gap"
        return "BUY INITIAL", "Trigger Cross"
    if sig_kind == SignalKind.PARTIAL_TP1:
        if exit_reason == "TP1_AVG":
            return "TP1 AVG EXIT", "Averaging TP1"
        return "TP1 EXIT", "Partial Book"
    if sig_kind == SignalKind.CLOSE_TP2:
        return "TP2 EXIT", "Adaptive Trail"
    if sig_kind == SignalKind.CLOSE_SL:
        return "SL EXIT", "Stop Loss Hit"
    if sig_kind == SignalKind.CLOSE_SESSION:
        return "SESSION EXIT", "Square Off"
    return exit_reason or sig_kind.value, exit_reason or ""


def _build_cycle_trade_records(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group event log into one professional record per trade cycle."""
    groups: dict[str, list[dict[str, Any]]] = {}
    order_keys: list[str] = []
    for row in log:
        key = f"{row.get('date')}|{row.get('cycle_id')}"
        if key not in groups:
            groups[key] = []
            order_keys.append(key)
        groups[key].append(row)

    records: list[dict[str, Any]] = []
    for order, key in enumerate(order_keys, 1):
        rows = groups[key]
        if not rows:
            continue

        first = rows[0]
        side = str(first.get("side") or "")
        entry_type = str(first.get("entry_type") or "INITIAL")
        cycle_kind = "REENTRY" if entry_type == "REENTRY" else "INITIAL"

        rec: dict[str, Any] = {
            "order": order,
            "date": first.get("date"),
            "cycle_id": first.get("cycle_id"),
            "side": side,
            "cycle_kind": cycle_kind,
            "base_price": None,
            "trigger_price": None,
            "initial_entry": None,
            "averaging": [],
            "tp1_price": None,
            "tp1_exit_lots": 0,
            "tp1_time": None,
            "tp2_adaptive_high": None,
            "tp2_adaptive_low": None,
            "tp2_exit_price": None,
            "tp2_time": None,
            "stop_loss": None,
            "reentry_price": None,
            "reentry_strike": None,
            "exit_reason": "",
            "total_lots_used": 0,
            "cycle_pnl": 0.0,
            "running_pnl": 0.0,
        }

        entry_lots_sum = 0
        for row in rows:
            action = str(row.get("action") or "").upper()
            et = str(row.get("entry_type") or "")
            strike_lbl = str(row.get("selected_strike_label") or _strike_label(float(row.get("strike") or 0), side))

            if action in ("BUY", "AVERAGE"):
                leg = {
                    "label": str(row.get("action_label") or action),
                    "time": row.get("time"),
                    "index_price": row.get("current_index_price") or row.get("index_price"),
                    "strike": strike_lbl,
                    "strike_type": row.get("strike_type") or row.get("strike_selection"),
                    "lots": row.get("lots_added") or row.get("lots"),
                }
                if et in ("INITIAL", "REENTRY"):
                    rec["base_price"] = row.get("base_price")
                    rec["trigger_price"] = row.get("trigger_price")
                    rec["stop_loss"] = row.get("stop_loss")
                    rec["initial_entry"] = leg
                    if et == "REENTRY":
                        rec["reentry_price"] = row.get("trigger_price") or row.get("index_price")
                        rec["reentry_strike"] = strike_lbl
                    entry_lots_sum += int(row.get("lots_added") or row.get("lots") or 0)
                elif et == "AVERAGE" or action == "AVERAGE":
                    rec["averaging"].append(leg)
                    entry_lots_sum += int(row.get("lots_added") or row.get("lots") or 0)

            elif action == "TP1_PARTIAL":
                rec["tp1_price"] = row.get("exit_price") or row.get("tp1")
                rec["tp1_exit_lots"] = int(rec.get("tp1_exit_lots") or 0) + int(row.get("exit_lots") or row.get("lots") or 0)
                rec["tp1_time"] = row.get("time")
                if rec.get("stop_loss") is None:
                    rec["stop_loss"] = row.get("stop_loss")

            elif action == "EXIT":
                reason = str(row.get("exit_reason") or "")
                rec["exit_reason"] = reason
                rec["tp2_exit_price"] = row.get("exit_price")
                rec["tp2_time"] = row.get("time")
                if row.get("adaptive_high") is not None:
                    rec["tp2_adaptive_high"] = row.get("adaptive_high")
                if row.get("adaptive_low") is not None:
                    rec["tp2_adaptive_low"] = row.get("adaptive_low")
                if rec.get("stop_loss") is None:
                    rec["stop_loss"] = row.get("stop_loss")

            pnl = float(row.get("trade_pnl") or 0)
            if pnl:
                rec["cycle_pnl"] = round(float(rec["cycle_pnl"]) + pnl, 2)
            if row.get("running_pnl") is not None:
                rec["running_pnl"] = row.get("running_pnl")

        rec["total_lots_used"] = entry_lots_sum
        rec["cycle_pnl"] = round(float(rec.get("cycle_pnl") or 0), 2)
        records.append(rec)

    return records


def _compute_cycle_stats(log: list[dict[str, Any]]) -> dict[str, Any]:
    cycles = {str(r.get("cycle_id")) for r in log if r.get("cycle_id") is not None}
    initial_cycles = {
        str(r.get("cycle_id"))
        for r in log
        if str(r.get("action_label") or "").startswith("BUY INITIAL")
    }
    reentry_cycles = {
        str(r.get("cycle_id"))
        for r in log
        if str(r.get("action_label") or "") in ("REENTRY", "BUY REENTRY")
    }
    avg_events = sum(1 for r in log if "AVG" in str(r.get("action_label") or ""))
    exit_events = sum(
        1
        for r in log
        if str(r.get("action") or "") in ("TP1_PARTIAL", "EXIT")
    )
    max_avg = 0
    per_cycle_avg: dict[str, int] = {}
    for r in log:
        lbl = str(r.get("action_label") or "")
        if "AVG" in lbl:
            cid = str(r.get("cycle_id"))
            per_cycle_avg[cid] = per_cycle_avg.get(cid, 0) + 1
            max_avg = max(max_avg, per_cycle_avg[cid])
    return {
        "trade_cycles": len(cycles),
        "initial_cycles": len(initial_cycles),
        "reentry_cycles": len(reentry_cycles),
        "exit_events": exit_events,
        "averaging_events": avg_events,
        "max_averaging_per_cycle": max_avg,
        "avg_entries_per_cycle": round(avg_events / max(len(cycles), 1), 2),
    }


def run_day_backtest(
    *,
    trade_date: str,
    candles: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    p = TrendParams.from_config(cfg)
    start_time = str(cfg.get("startTime") or "09:15")
    end_time = str(cfg.get("endTime") or "15:30")
    auto_sq = str(cfg.get("autoSquareOffTime") or end_time)

    base = _find_base_close(candles, start_time)
    if base is None or base < 1000:
        return {"date": trade_date, "ok": False, "message": "No base candle", "trades": [], "log": []}

    state = EngineState(base_price=base)
    log: list[dict[str, Any]] = []
    closed_trades: list[dict[str, Any]] = []
    running_pnl = 0.0
    trade_id = 0
    open_meta: dict[int, dict[str, Any]] = {}

    session_candles = [c for c in candles if _in_window(str(c.get("time", "")), start_time, end_time)]
    if len(session_candles) < 2:
        return {"date": trade_date, "ok": False, "message": "Insufficient candles", "trades": [], "log": []}

    prev_close: float | None = None
    chart_candles: list[dict[str, Any]] = []
    cycle_avg_count: dict[int, int] = {}
    cycle_lots: dict[int, int] = {}
    cycle_index_sum: dict[int, float] = {}
    for i, c in enumerate(session_candles):
        t = str(c.get("time", ""))
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        session_end = _at_or_after(t, auto_sq)

        bar = BarSlice(time=t, open=o, high=h, low=l, close=cl, prev_close=prev_close)
        state, signals = process_bar(state, p, bar, session_end=session_end)

        chart_candles.append(
            {
                "time": _short_time(t),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(cl, 2),
                "adaptive_high": round(state.adaptive_high, 2) if state.adaptive_high is not None else None,
                "adaptive_low": round(state.adaptive_low, 2) if state.adaptive_low is not None else None,
            }
        )

        for sig in signals:
            oc = state.open_cycle
            if sig.sl_level is not None:
                sl = round(float(sig.sl_level), 2)
            elif oc is not None and oc.cycle_id == sig.cycle_id:
                sl = round(cycle_sl_for_open(oc, p), 2)
            else:
                sl = round(cycle_sl(sig.side, sig.cycle_base, p), 2)
            tp2 = oc.trail_extreme if oc is not None and oc.cycle_id == sig.cycle_id else None
            avg_idx = cycle_avg_count.get(sig.cycle_id, 0)
            if sig.kind == SignalKind.OPEN_AVERAGE:
                avg_idx += 1
                cycle_avg_count[sig.cycle_id] = avg_idx
            action_label, reason_label = _log_labels(sig.kind, sig.entry_kind, sig.exit_reason, avg_idx)
            lots_this = sig.lots
            if sig.kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE):
                prev_lots = cycle_lots.get(sig.cycle_id, 0)
                new_total = prev_lots + lots_this
                cycle_lots[sig.cycle_id] = new_total
                cycle_index_sum[sig.cycle_id] = (
                    cycle_index_sum.get(sig.cycle_id, 0.0) + float(sig.price) * lots_this
                )
                avg_entry_px = (
                    round(cycle_index_sum[sig.cycle_id] / new_total, 2) if new_total > 0 else round(sig.price, 2)
                )
            else:
                new_total = cycle_lots.get(sig.cycle_id, 0)
                avg_entry_px = (
                    round(cycle_index_sum.get(sig.cycle_id, 0) / new_total, 2)
                    if new_total > 0
                    else round(sig.first_entry, 2)
                )

            trigger_px = round(sig.price, 2)
            if sig.entry_kind in (EntryKind.INITIAL, EntryKind.REENTRY):
                trigger_px = round(sig.first_entry, 2)
            strike_mode = "Nearest" if sig.entry_kind == EntryKind.AVERAGE else "Offset"
            row_base = round(base, 2) if sig.entry_kind == EntryKind.INITIAL else round(sig.cycle_base, 2)
            lots_added = lots_this if sig.kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE) else 0
            tp1_val = round(sig.t1_level, 2) if sig.t1_level is not None else None

            row = {
                "date": trade_date,
                "time": _short_time(t),
                "cycle_id": sig.cycle_id,
                "side": sig.side,
                "action": sig.kind.value,
                "action_label": action_label,
                "reason_label": reason_label,
                "trigger_mode": "intrabar_touch",
                "entry_type": sig.entry_kind.value,
                "index_price": round(sig.price, 2),
                "current_index_price": round(sig.price, 2),
                "base_price": row_base,
                "trigger_price": trigger_px,
                "strike_offset": p.strike_offset if sig.entry_kind != EntryKind.AVERAGE else None,
                "strike_selection": strike_mode,
                "strike_type": strike_mode,
                "strike": round(sig.strike, 2),
                "selected_strike": round(sig.strike, 2),
                "selected_strike_label": _strike_label(sig.strike, sig.side),
                "average_level": avg_idx if sig.entry_kind == EntryKind.AVERAGE else None,
                "average_entry_price": avg_entry_px,
                "lots": lots_this,
                "lots_added": lots_added,
                "exit_lots": None,
                "remaining_lots": new_total if sig.kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE) else None,
                "total_lots": new_total if sig.kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE) else cycle_lots.get(sig.cycle_id),
                "tp1": tp1_val,
                "tp2_trail": p.tp2_trail,
                "tp2": round(tp2, 2) if tp2 is not None else None,
                "stop_loss": sl,
                "adaptive_ref": round(sig.cycle_base, 2),
                "adaptive_high": round(sig.adaptive_extreme, 2)
                if sig.adaptive_extreme is not None and sig.side == "CALL"
                else (round(state.adaptive_high, 2) if state.adaptive_high is not None else None),
                "adaptive_low": round(sig.adaptive_extreme, 2)
                if sig.adaptive_extreme is not None and sig.side == "PUT"
                else (round(state.adaptive_low, 2) if state.adaptive_low is not None else None),
                "exit_price": None,
                "exit_reason": sig.exit_reason,
                "trade_pnl": 0.0,
                "running_pnl": round(running_pnl, 2),
                "strike_detail": _strike_detail(
                    entry_kind=sig.entry_kind,
                    side=sig.side,
                    base_price=row_base if sig.entry_kind == EntryKind.INITIAL else trigger_px,
                    trigger_price=trigger_px,
                    index_price=round(sig.price, 2),
                    strike=sig.strike,
                    strike_offset=p.strike_offset,
                    avg_level=avg_idx if sig.entry_kind == EntryKind.AVERAGE else None,
                ),
            }

            if sig.kind in (SignalKind.OPEN_INITIAL, SignalKind.OPEN_AVERAGE):
                if sig.kind == SignalKind.OPEN_AVERAGE:
                    row["action"] = "AVERAGE"
                    row["lots"] = sig.lots
                else:
                    row["action"] = "BUY"
                open_meta.setdefault(sig.cycle_id, []).append(
                    {"side": sig.side, "entry": sig.price, "lots": row["lots"], "entry_type": sig.entry_kind.value}
                )
            elif sig.kind == SignalKind.PARTIAL_TP1:
                row["action"] = "TP1_PARTIAL"
                row["exit_price"] = round(sig.price, 2)
                row["exit_lots"] = sig.close_lots
                row["lots"] = sig.close_lots
                row["lots_added"] = 0
                row["tp1"] = round(sig.t1_level, 2)
                row["selected_strike_label"] = _strike_label(sig.strike, sig.side)
                remaining = max(0, cycle_lots.get(sig.cycle_id, sig.lots) - sig.close_lots)
                cycle_lots[sig.cycle_id] = remaining
                row["remaining_lots"] = remaining
                row["total_lots"] = remaining
                pnl = points_pnl(sig.side, sig.first_entry, sig.price, sig.close_lots)
                row["trade_pnl"] = pnl
                running_pnl += pnl
                row["running_pnl"] = round(running_pnl, 2)
                trade_id += 1
                closed_trades.append({**row, "id": trade_id, "entry": sig.first_entry})
            elif sig.kind in (SignalKind.CLOSE_TP2, SignalKind.CLOSE_SL, SignalKind.CLOSE_SESSION):
                row["action"] = "EXIT"
                row["exit_price"] = round(sig.price, 2)
                row["exit_lots"] = sig.lots
                row["lots"] = sig.lots
                row["lots_added"] = 0
                row["remaining_lots"] = 0
                row["total_lots"] = 0
                row["selected_strike_label"] = _strike_label(sig.strike, sig.side)
                if sig.adaptive_extreme is not None:
                    if sig.side == "CALL":
                        row["adaptive_high"] = round(sig.adaptive_extreme, 2)
                    else:
                        row["adaptive_low"] = round(sig.adaptive_extreme, 2)
                pnl = points_pnl(sig.side, sig.first_entry, sig.price, sig.lots)
                row["trade_pnl"] = pnl
                running_pnl += pnl
                row["running_pnl"] = round(running_pnl, 2)
                trade_id += 1
                closed_trades.append(
                    {
                        **row,
                        "id": trade_id,
                        "entry": sig.first_entry,
                        "reason": sig.exit_reason,
                    }
                )
                cycle_lots.pop(sig.cycle_id, None)
                cycle_index_sum.pop(sig.cycle_id, None)
                cycle_avg_count.pop(sig.cycle_id, None)
                state.daily_pnl_points = running_pnl

            log.append(row)

        prev_close = cl

    call_trig = round(base + p.entry_trigger, 2)
    put_trig = round(base - p.entry_trigger, 2)

    return {
        "date": trade_date,
        "ok": True,
        "base": round(base, 2),
        "call_trigger": call_trig,
        "put_trigger": put_trig,
        "points": round(running_pnl, 2),
        "trades": closed_trades,
        "log": log,
        "candles": chart_candles,
        "cycle_stats": _compute_cycle_stats(log),
        "planned_levels": _planned_levels(base, p),
        "timeline": _timeline_from_log(log, base=base, call_trig=call_trig, put_trig=put_trig),
    }


def _compute_stats(trades: list[dict[str, Any]], initial_capital: float = 0.0) -> dict[str, Any]:
    if not trades:
        return {
            "total_pnl": 0.0,
            "net_profit": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "expectancy": 0.0,
            "largest_profit": 0.0,
            "largest_loss": 0.0,
            "return_pct": 0.0,
        }

    pnls = [float(t.get("trade_pnl") or 0) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    total = sum(pnls)

    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    streak_w = streak_l = max_w = max_l = 0
    for p in pnls:
        if p > 0:
            streak_w += 1
            streak_l = 0
            max_w = max(max_w, streak_w)
        elif p < 0:
            streak_l += 1
            streak_w = 0
            max_l = max(max_l, streak_l)
        else:
            streak_w = streak_l = 0

    n = len(pnls)
    wr = len(wins) / n * 100 if n else 0
    lr = len(losses) / n * 100 if n else 0
    pf = gross_profit / abs(gross_loss) if gross_loss < 0 else (gross_profit if gross_profit > 0 else 0)
    avg_w = gross_profit / len(wins) if wins else 0
    avg_l = gross_loss / len(losses) if losses else 0
    exp = total / n if n else 0

    return {
        "total_pnl": round(total, 2),
        "net_profit": round(total, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "win_rate": round(wr, 2),
        "loss_rate": round(lr, 2),
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "profit_factor": round(pf, 4),
        "max_drawdown": round(max_dd, 2),
        "max_consecutive_wins": max_w,
        "max_consecutive_losses": max_l,
        "avg_win": round(avg_w, 2),
        "avg_loss": round(avg_l, 2),
        "expectancy": round(exp, 2),
        "largest_profit": round(max(wins) if wins else 0, 2),
        "largest_loss": round(min(losses) if losses else 0, 2),
        "return_pct": round((total / abs(initial_capital) * 100) if initial_capital else 0, 2),
    }


def run_range_backtest(
    *,
    days: list[dict[str, Any]],
    cfg: dict[str, Any],
    initial_capital: float = 0.0,
) -> dict[str, Any]:
    """days: [{date, candles: [{time,open,high,low,close}, ...]}, ...]"""
    all_trades: list[dict[str, Any]] = []
    all_log: list[dict[str, Any]] = []
    daily_summary: list[dict[str, Any]] = []
    day_details: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    running = initial_capital

    global_trade_id = 0
    for day in days:
        date = str(day.get("date") or "")
        candles = day.get("candles") if isinstance(day.get("candles"), list) else []
        out = run_day_backtest(trade_date=date, candles=candles, cfg=cfg)
        if not out.get("ok"):
            daily_summary.append({"date": date, "base": None, "points": 0, "trades": 0, "message": out.get("message")})
            continue
        pts = float(out.get("points") or 0)
        running += pts
        daily_summary.append(
            {
                "date": date,
                "base": out.get("base"),
                "call_trigger": out.get("call_trigger"),
                "put_trigger": out.get("put_trigger"),
                "points": pts,
                "trades": len(out.get("trades") or []),
            }
        )
        day_details.append(
            {
                "date": date,
                "base": out.get("base"),
                "call_trigger": out.get("call_trigger"),
                "put_trigger": out.get("put_trigger"),
                "points": pts,
                "candles": out.get("candles") or [],
                "planned_levels": out.get("planned_levels") or [],
                "timeline": out.get("timeline") or [],
            }
        )
        equity_curve.append({"date": date, "equity": round(running, 2), "daily_pnl": pts})
        for t in out.get("trades") or []:
            global_trade_id += 1
            t["id"] = global_trade_id
            all_trades.append(t)
        for row in out.get("log") or []:
            all_log.append(row)

    stats = _compute_stats(all_trades, initial_capital)
    stats["final_capital"] = round(initial_capital + stats["total_pnl"], 2)
    stats["closed_trades"] = len(all_trades)
    stats["exit_events"] = len(all_trades)
    cycle_stats = _compute_cycle_stats(all_log)
    stats.update(cycle_stats)

    drawdown_curve = []
    peak = initial_capital
    eq = initial_capital
    for pt in equity_curve:
        eq = float(pt["equity"])
        peak = max(peak, eq)
        drawdown_curve.append({"date": pt["date"], "drawdown": round(peak - eq, 2)})

    return {
        "ok": bool(all_trades or daily_summary),
        "stats": stats,
        "trades": all_trades,
        "log": all_log,
        "cycle_records": _build_cycle_trade_records(all_log),
        "daily_summary": daily_summary,
        "day_details": day_details,
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "params": asdict(TrendParams.from_config(cfg)),
    }
