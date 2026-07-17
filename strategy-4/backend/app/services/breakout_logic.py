"""Strategy 4 — MCX single breakout with one reverse entry (pure logic)."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Literal

Side = Literal["BUY", "SELL"]
Phase = Literal[
    "IDLE",
    "WAIT_REF",
    "WAIT_BREAKOUT",
    "IN_TRADE",
    "REVERSE_TRADE",
    "DONE",
    "NO_TRADE",
]


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_hhmm(value: str) -> tuple[int, int]:
    parts = (value or "09:00").strip().split(":")
    h = int(parts[0]) if parts and parts[0].isdigit() else 9
    m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return h, m


def hhmm_from_candle_time(time_str: str) -> str | None:
    if not time_str:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", str(time_str))
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_strategy_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    c = cfg or {}
    return {
        "start_time": str(c.get("startTime") or "18:29"),
        "end_time": str(c.get("endTime") or "23:30"),
        "market": str(c.get("market") or "CRUDE_OIL").upper(),
        "lots": max(1, _int(c.get("lotSize") or c.get("lots") or c.get("initialLots"), 1)),
        "breakout_distance": max(0.01, _num(c.get("breakoutDistance"), 0.5)),
        "take_profit": max(0.01, _num(c.get("takeProfit"), 1.0)),
        "stop_loss": max(0.01, _num(c.get("stopLoss"), 0.8)),
    }


def compute_triggers(reference_price: float, breakout_distance: float) -> tuple[float, float]:
    ref = round(reference_price, 4)
    dist = round(breakout_distance, 4)
    return round(ref + dist, 4), round(ref - dist, 4)


def compute_tp_sl(side: Side, entry: float, tp_pts: float, sl_pts: float) -> tuple[float, float]:
    entry = round(entry, 4)
    if side == "BUY":
        return round(entry + tp_pts, 4), round(entry - sl_pts, 4)
    return round(entry - tp_pts, 4), round(entry + sl_pts, 4)


def default_runtime() -> dict[str, Any]:
    return {
        "phase": "IDLE",
        "sessionDate": "",
        "referencePrice": 0.0,
        "buyTrigger": 0.0,
        "sellTrigger": 0.0,
        "side": None,
        "entryPrice": 0.0,
        "tpPrice": 0.0,
        "slPrice": 0.0,
        "isReverse": False,
        "tradeCount": 0,
        "positionLots": 0,
        "realizedPnl": 0.0,
        "lastPrice": 0.0,
        "prevPrice": 0.0,
        "refCandleTime": "",
        "reverseEntryBarTime": "",
        "message": "",
    }


def fresh_breakout_runtime(*, session_date: str = "", last_price: float = 0.0) -> dict[str, Any]:
    rt = default_runtime()
    rt["sessionDate"] = session_date
    rt["lastPrice"] = round(last_price, 4) if last_price > 0 else 0.0
    rt["phase"] = "WAIT_REF" if session_date else "IDLE"
    return rt


def _reference_matches_ltp(ref: float, ltp: float) -> bool:
    """Reject stale refs from a different instrument (e.g. NG ~280 vs Crude ~7600)."""
    if ref <= 0 or ltp <= 0:
        return True
    ratio = ref / ltp
    return 0.4 <= ratio <= 2.5


def align_runtime_to_config(
    runtime: dict[str, Any],
    parsed: dict[str, Any],
    *,
    symbol: str = "",
    last_price: float = 0.0,
) -> tuple[dict[str, Any], bool]:
    """
    Keep breakout runtime bound to the current settings market/start time.
    Returns (runtime, changed) — changed=True when reference/session must re-arm.
    """
    rt = deepcopy(runtime)
    market = str(parsed.get("market") or "").upper()
    start = str(parsed.get("start_time") or "")
    dist = float(parsed.get("breakout_distance") or 0)
    rt_market = str(rt.get("market") or "").upper()
    rt_start = str(rt.get("startTime") or "")
    open_lots = int(rt.get("positionLots") or 0)
    phase = str(rt.get("phase") or "")
    in_trade = open_lots > 0 and phase in ("IN_TRADE", "REVERSE_TRADE")

    if in_trade:
        if market and not rt_market:
            rt["market"] = market
            return rt, True
        return rt, False

    mismatch = bool(rt_market and market and rt_market != market)
    start_changed = bool(rt_start and start and rt_start != start)
    bad_ref = bool(
        _num(rt.get("referencePrice")) > 0
        and last_price > 0
        and not _reference_matches_ltp(_num(rt.get("referencePrice")), last_price)
    )

    if mismatch or start_changed or bad_ref:
        reason = (
            f"market {rt_market}->{market}"
            if mismatch
            else (f"start {rt_start}->{start}" if start_changed else "reference mismatch vs LTP")
        )
        session = str(rt.get("sessionDate") or "")
        cleared = fresh_breakout_runtime(session_date=session, last_price=last_price or _num(rt.get("lastPrice")))
        cleared["market"] = market
        cleared["startTime"] = start
        cleared["breakoutDistance"] = dist
        cleared["refSymbol"] = symbol or ""
        cleared["message"] = f"Settings changed ({reason}) — re-arming reference for {market or 'market'}"
        return cleared, True

    changed = False
    # Same market: keep ref, but rebuild triggers if distance changed.
    if _num(rt.get("referencePrice")) > 0 and dist > 0:
        old_dist = _num(rt.get("breakoutDistance"))
        if old_dist > 0 and abs(old_dist - dist) > 1e-9:
            buy_trig, sell_trig = compute_triggers(_num(rt.get("referencePrice")), dist)
            rt["buyTrigger"] = buy_trig
            rt["sellTrigger"] = sell_trig
            rt["breakoutDistance"] = dist
            if phase == "WAIT_BREAKOUT":
                rt["message"] = (
                    f"Reference close {_num(rt.get('referencePrice')):.2f} · "
                    f"Buy {buy_trig:.2f} · Sell {sell_trig:.2f}"
                )
            changed = True

    if market and rt.get("market") != market:
        rt["market"] = market
        changed = True
    if start and rt.get("startTime") != start:
        rt["startTime"] = start
        changed = True
    if dist > 0 and abs(_num(rt.get("breakoutDistance")) - dist) > 1e-9:
        rt["breakoutDistance"] = dist
        changed = True
    if symbol and rt.get("refSymbol") != symbol:
        rt["refSymbol"] = symbol
        changed = True
    return rt, changed


def load_runtime(cfg: dict[str, Any]) -> dict[str, Any]:
    rt = cfg.get("breakout_runtime")
    base = default_runtime()
    if isinstance(rt, dict):
        base.update(rt)
    return base


def save_runtime(cfg: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(cfg)
    out["breakout_runtime"] = runtime
    return out


def find_reference_candle(candles: list[dict[str, Any]], start_time: str) -> dict[str, Any] | None:
    target = start_time.strip()[:5]
    for c in candles:
        hhmm = hhmm_from_candle_time(str(c.get("time") or ""))
        if hhmm == target:
            close = _num(c.get("close"))
            if close > 0:
                return c
    return None


def set_reference_from_candle(runtime: dict[str, Any], candle: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    rt = deepcopy(runtime)
    ref = round(_num(candle.get("close")), 4)
    buy_trig, sell_trig = compute_triggers(ref, parsed["breakout_distance"])
    rt.update(
        {
            "phase": "WAIT_BREAKOUT",
            "referencePrice": ref,
            "buyTrigger": buy_trig,
            "sellTrigger": sell_trig,
            "refCandleTime": str(candle.get("time") or ""),
            "market": str(parsed.get("market") or rt.get("market") or "").upper(),
            "startTime": str(parsed.get("start_time") or rt.get("startTime") or ""),
            "breakoutDistance": float(parsed.get("breakout_distance") or 0),
            "message": f"Reference close {ref:.2f} · Buy {buy_trig:.2f} · Sell {sell_trig:.2f}",
        }
    )
    return rt


def _pnl_delta(side: Side, entry: float, exit_px: float, lots: int) -> float:
    if side == "BUY":
        return (exit_px - entry) * lots
    return (entry - exit_px) * lots


def _bar_path(open_px: float, high: float, low: float, close: float) -> list[float]:
    if close >= open_px:
        return [open_px, low, high, close]
    return [open_px, high, low, close]


def _touch_level_on_path(path: list[float], level: float, *, side: Side) -> bool:
    prev = path[0]
    for px in path[1:]:
        lo, hi = (px, prev) if px < prev else (prev, px)
        if side == "BUY" and hi >= level - 1e-9:
            return True
        if side == "SELL" and lo <= level + 1e-9:
            return True
        prev = px
    return False


def _both_triggers_on_path(path: list[float], buy_trig: float, sell_trig: float) -> bool:
    return _touch_level_on_path(path, buy_trig, side="BUY") and _touch_level_on_path(path, sell_trig, side="SELL")


EXECUTION_POLICY = {
    "breakoutSameBarRule": "If open >= reference close, check BUY trigger before SELL along OHLC path; otherwise SELL before BUY.",
    "exitSameBarRule": "On each path segment, Stop Loss is evaluated before Take Profit (conservative). Reverse TP/SL is evaluated from the next candle onward (not same bar as reverse entry).",
    "reverseEntryPrice": "Opposite entry at the Stop Loss fill price immediately after initial SL.",
    "maxTradesPerDay": 2,
}


def format_time_label(time_str: str) -> str:
    hhmm = hhmm_from_candle_time(time_str)
    return hhmm or str(time_str)[:16]


def _minutes_between(t0: str, t1: str) -> int | None:
    m0 = re.search(r"(\d{1,2}):(\d{2})", str(t0))
    m1 = re.search(r"(\d{1,2}):(\d{2})", str(t1))
    if not m0 or not m1:
        return None
    a = int(m0.group(1)) * 60 + int(m0.group(2))
    b = int(m1.group(1)) * 60 + int(m1.group(2))
    return max(0, b - a)


def _first_breakout(side_order: list[Side], buy_trig: float, sell_trig: float, path: list[float]) -> tuple[Side | None, float]:
    prev = path[0]
    for px in path[1:]:
        lo, hi = (px, prev) if px < prev else (prev, px)
        for side in side_order:
            if side == "BUY" and hi >= buy_trig - 1e-9:
                return "BUY", buy_trig
            if side == "SELL" and lo <= sell_trig + 1e-9:
                return "SELL", sell_trig
        prev = px
    return None, 0.0


def _check_exit(side: Side, tp: float, sl: float, path: list[float]) -> tuple[str | None, float]:
    """Return (TP|SL, fill_price) for first hit along path. SL checked before TP on each segment (conservative)."""
    prev = path[0]
    for px in path[1:]:
        lo, hi = (px, prev) if px < prev else (prev, px)
        if side == "BUY":
            if lo <= sl + 1e-9:
                return "SL", sl
            if hi >= tp - 1e-9:
                return "TP", tp
        else:
            if hi >= sl - 1e-9:
                return "SL", sl
            if lo <= tp + 1e-9:
                return "TP", tp
        prev = px
    return None, 0.0


def _open_entry(
    *,
    side: Side,
    fill: float,
    parsed: dict[str, Any],
    rt: dict[str, Any],
    is_reverse: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tp, sl = compute_tp_sl(side, fill, parsed["take_profit"], parsed["stop_loss"])
    phase: Phase = "REVERSE_TRADE" if is_reverse else "IN_TRADE"
    lots = parsed["lots"]
    new_rt = deepcopy(rt)
    new_rt.update(
        {
            "phase": phase,
            "side": side,
            "entryPrice": round(fill, 4),
            "tpPrice": tp,
            "slPrice": sl,
            "isReverse": is_reverse,
            "tradeCount": _int(rt.get("tradeCount")) + 1,
            "positionLots": lots,
        }
    )
    label = "REVERSE" if is_reverse else "INITIAL"
    entry_type = "Reverse" if is_reverse else "Initial"
    action = {
        "action": f"{label}_{side}",
        "side": side,
        "fillPrice": round(fill, 4),
        "lots": lots,
        "tpPrice": tp,
        "slPrice": sl,
        "isReverse": is_reverse,
        "entryType": entry_type,
        "realizedPnl": round(_num(rt.get("realizedPnl")), 2),
        "runningDayPnl": round(_num(rt.get("realizedPnl")), 2),
        "message": f"{label} {side} {lots} lot(s) @ {fill:.2f} · TP {tp:.2f} · SL {sl:.2f}",
    }
    return new_rt, action


def _close_position(
    *,
    rt: dict[str, Any],
    parsed: dict[str, Any],
    reason: str,
    exit_px: float,
    allow_reverse: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    side = rt.get("side")
    if side not in ("BUY", "SELL"):
        return rt, actions
    side = side  # type: Side
    entry = _num(rt.get("entryPrice"))
    lots = _int(rt.get("positionLots")) or parsed["lots"]
    realized = _num(rt.get("realizedPnl")) + _pnl_delta(side, entry, exit_px, lots)
    is_reverse = bool(rt.get("isReverse"))

    trade_pnl = round(_pnl_delta(side, entry, exit_px, lots), 2)
    actions.append(
        {
            "action": f"EXIT_{reason}",
            "side": side,
            "fillPrice": round(exit_px, 4),
            "lots": lots,
            "entryPrice": round(entry, 4),
            "exitPrice": round(exit_px, 4),
            "exitReason": reason,
            "isReverse": is_reverse,
            "entryType": "Reverse" if is_reverse else "Initial",
            "tradePnl": trade_pnl,
            "realizedPnl": round(realized, 2),
            "runningDayPnl": round(realized, 2),
            "message": f"{'Reverse' if is_reverse else 'Initial'} {side} exit {reason} @ {exit_px:.2f} · Leg PnL {trade_pnl:.2f} · Day {realized:.2f}",
        }
    )

    new_rt = deepcopy(rt)
    new_rt.update(
        {
            "positionLots": 0,
            "realizedPnl": round(realized, 2),
            "entryPrice": 0.0,
            "tpPrice": 0.0,
            "slPrice": 0.0,
            "side": None,
        }
    )

    if reason == "TP" or reason == "EOD" or is_reverse or not allow_reverse:
        new_rt["phase"] = "DONE"
        new_rt["message"] = "Strategy complete for the day"
        return new_rt, actions

    # Initial SL → reverse once
    rev_side: Side = "SELL" if side == "BUY" else "BUY"
    new_rt, rev_action = _open_entry(side=rev_side, fill=exit_px, parsed=parsed, rt=new_rt, is_reverse=True)
    actions.append(rev_action)
    return new_rt, actions


def _path_after_trigger(path: list[float], side: Side, trigger: float) -> list[float]:
    """Sub-path from first trigger touch through end of bar."""
    if not path:
        return path
    out = [trigger]
    started = False
    prev = path[0]
    for px in path[1:]:
        lo, hi = (px, prev) if px < prev else (prev, px)
        if not started:
            if side == "BUY" and hi >= trigger - 1e-9:
                started = True
            elif side == "SELL" and lo <= trigger + 1e-9:
                started = True
        if started:
            out.append(px)
        prev = px
    return out if len(out) > 1 else [trigger, path[-1]]


def process_candle(
    cfg: dict[str, Any],
    runtime: dict[str, Any],
    candle: dict[str, Any],
    *,
    after_reference: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Process one 1-min OHLC candle. Set after_reference=False only for the reference candle itself."""
    parsed = parse_strategy_config(cfg)
    rt = deepcopy(runtime)
    actions: list[dict[str, Any]] = []
    o, h, l, c = (_num(candle.get("open")), _num(candle.get("high")), _num(candle.get("low")), _num(candle.get("close")))
    if min(o, h, l, c) <= 0:
        return rt, actions

    rt["lastPrice"] = round(c, 4)
    phase = str(rt.get("phase") or "IDLE")

    if not after_reference:
        return rt, actions

    if phase in ("DONE", "NO_TRADE"):
        return rt, actions

    path = _bar_path(o, h, l, c)
    ref = _num(rt.get("referencePrice"))
    buy_trig = _num(rt.get("buyTrigger"))
    sell_trig = _num(rt.get("sellTrigger"))

    if phase == "WAIT_BREAKOUT" and ref > 0:
        ref_px = _num(rt.get("referencePrice"))
        side_order: list[Side] = ["BUY", "SELL"] if o >= ref_px else ["SELL", "BUY"]
        side, fill = _first_breakout(side_order, buy_trig, sell_trig, path)
        if side is None:
            return rt, actions
        rt, entry_action = _open_entry(side=side, fill=fill, parsed=parsed, rt=rt, is_reverse=False)
        entry_action["sameBarAmbiguity"] = _both_triggers_on_path(path, buy_trig, sell_trig)
        actions.append(entry_action)
        rem_path = _path_after_trigger(path, side, fill)
        exit_reason, exit_px = _check_exit(side, _num(rt.get("tpPrice")), _num(rt.get("slPrice")), rem_path)
        if exit_reason:
            allow_rev = exit_reason == "SL"
            rt, exit_actions = _close_position(rt=rt, parsed=parsed, reason=exit_reason, exit_px=exit_px, allow_reverse=allow_rev)
            actions.extend(exit_actions)
            if allow_rev and str(rt.get("phase")) == "REVERSE_TRADE":
                rt["reverseEntryBarTime"] = str(candle.get("time") or "")
        return rt, actions

    if phase in ("IN_TRADE", "REVERSE_TRADE") and rt.get("side") in ("BUY", "SELL"):
        if phase == "REVERSE_TRADE" and str(rt.get("reverseEntryBarTime") or "") == str(candle.get("time") or ""):
            return rt, actions
        side = rt["side"]  # type: Side
        tp = _num(rt.get("tpPrice"))
        sl = _num(rt.get("slPrice"))
        exit_reason, exit_px = _check_exit(side, tp, sl, path)
        if not exit_reason:
            return rt, actions
        allow_rev = exit_reason == "SL" and phase == "IN_TRADE"
        rt, exit_actions = _close_position(
            rt=rt,
            parsed=parsed,
            reason=exit_reason,
            exit_px=exit_px,
            allow_reverse=allow_rev,
        )
        actions.extend(exit_actions)
        if allow_rev and str(rt.get("phase")) == "REVERSE_TRADE":
            rt["reverseEntryBarTime"] = str(candle.get("time") or "")

    return rt, actions


def build_round_trip_trades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair entry events with exits into audit-friendly round-trip rows."""
    trips: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    trip_id = 0
    for ev in events:
        act = str(ev.get("action") or "")
        if act.startswith("INITIAL_") or act.startswith("REVERSE_"):
            pending = ev
            continue
        if not act.startswith("EXIT_") or pending is None:
            continue
        trip_id += 1
        entry_px = float(pending.get("fillPrice") or 0)
        exit_px = float(ev.get("exitPrice") or ev.get("fillPrice") or 0)
        trips.append(
            {
                "id": trip_id,
                "tradeLabel": f"{pending.get('entryType')} {pending.get('side')}",
                "entryType": pending.get("entryType"),
                "side": pending.get("side"),
                "entryPrice": entry_px,
                "tpPrice": float(pending.get("tpPrice") or 0),
                "slPrice": float(pending.get("slPrice") or 0),
                "exitPrice": exit_px,
                "exitReason": ev.get("exitReason") or act.replace("EXIT_", ""),
                "tradePnl": float(ev.get("tradePnl") or 0),
                "runningDayPnl": float(ev.get("runningDayPnl") or 0),
                "entryTime": pending.get("time") or "",
                "exitTime": ev.get("time") or "",
                "durationMinutes": _minutes_between(str(pending.get("time") or ""), str(ev.get("time") or "")),
                "lots": int(pending.get("lots") or 0),
            }
        )
        pending = None
    return trips


def build_result_string(round_trips: list[dict[str, Any]], phase: str) -> str:
    if phase == "NO_TRADE":
        return "No breakout"
    if not round_trips:
        return phase or "—"
    initial = next((t for t in round_trips if t.get("entryType") == "Initial"), None)
    reverse = next((t for t in round_trips if t.get("entryType") == "Reverse"), None)
    if initial and not reverse:
        return str(initial.get("exitReason") or "—")
    if initial and reverse:
        return f"SL -> Reverse {reverse.get('side')} ({reverse.get('exitReason')})"
    return " → ".join(f"{t.get('entryType')} {t.get('side')} ({t.get('exitReason')})" for t in round_trips)


def build_timeline(
    *,
    start_time: str,
    reference_close: float,
    ref_candle_time: str,
    events: list[dict[str, Any]],
    phase: str,
    reference_open: float = 0.0,
    reference_high: float = 0.0,
    reference_low: float = 0.0,
    buy_trigger: float = 0.0,
    sell_trigger: float = 0.0,
    buy_trigger_touch_time: str | None = None,
    sell_trigger_touch_time: str | None = None,
    buy_trigger_touch_high: float | None = None,
    sell_trigger_touch_low: float | None = None,
) -> list[dict[str, str]]:
    ref_t = format_time_label(ref_candle_time) or start_time
    rows: list[dict[str, str]] = [
        {
            "time": ref_t,
            "label": "Reference Candle",
            "detail": f"O {reference_open:.2f} · H {reference_high:.2f} · L {reference_low:.2f} · C {reference_close:.2f}",
        }
    ]
    if buy_trigger > 0:
        if buy_trigger_touch_time:
            rows.append(
                {
                    "time": format_time_label(buy_trigger_touch_time),
                    "label": "Buy Trigger",
                    "detail": f"@{buy_trigger:.2f} · High {float(buy_trigger_touch_high or 0):.2f}",
                }
            )
        else:
            rows.append({"time": "", "label": "Buy Trigger", "detail": f"@{buy_trigger:.2f} · Not touched"})
    if sell_trigger > 0:
        if sell_trigger_touch_time:
            rows.append(
                {
                    "time": format_time_label(sell_trigger_touch_time),
                    "label": "Sell Trigger",
                    "detail": f"@{sell_trigger:.2f} · Low {float(sell_trigger_touch_low or 0):.2f}",
                }
            )
        else:
            rows.append({"time": "", "label": "Sell Trigger", "detail": f"@{sell_trigger:.2f} · Not touched"})
    for ev in events:
        act = str(ev.get("action") or "")
        t = format_time_label(str(ev.get("time") or ""))
        if act.startswith("INITIAL_") or act.startswith("REVERSE_"):
            tp = float(ev.get("tpPrice") or 0)
            sl = float(ev.get("slPrice") or 0)
            rows.append(
                {
                    "time": t,
                    "label": f"{ev.get('entryType')} {ev.get('side')}",
                    "detail": f"Entry @{float(ev.get('fillPrice') or 0):.2f} · TP {tp:.2f} · SL {sl:.2f}",
                }
            )
        elif act.startswith("EXIT_"):
            reason = ev.get("exitReason") or act.replace("EXIT_", "")
            pnl = float(ev.get("tradePnl") or 0)
            rows.append(
                {
                    "time": t,
                    "label": f"{reason} Hit",
                    "detail": f"Exit @{float(ev.get('exitPrice') or ev.get('fillPrice') or 0):.2f} · P&L {pnl:+.2f}",
                }
            )
    if phase == "DONE":
        rows.append({"time": rows[-1]["time"] if rows else "", "label": "Strategy Finished", "detail": ""})
    elif phase == "NO_TRADE":
        rows.append({"time": "", "label": "No Breakout", "detail": "Session ended without entry"})
    return rows


def build_day_chart_levels(
    *,
    reference_close: float,
    buy_trigger: float,
    sell_trigger: float,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    lid = 0
    def _add(**row: Any) -> None:
        nonlocal lid
        lid += 1
        levels.append({"id": lid, **row})

    _add(level="REF", price=reference_close, kind="reference", label="Reference Close")
    _add(level="BUY", price=buy_trigger, kind="buy_trigger", label="Buy Trigger")
    _add(level="SELL", price=sell_trigger, kind="sell_trigger", label="Sell Trigger")
    for ev in events:
        act = str(ev.get("action") or "")
        if act.startswith("INITIAL_") or act.startswith("REVERSE_"):
            prefix = "Initial" if ev.get("entryType") == "Initial" else "Reverse"
            _add(level=f"{prefix} Entry", price=float(ev.get("fillPrice") or 0), kind="entry", label=f"{prefix} Entry")
            _add(level=f"{prefix} TP", price=float(ev.get("tpPrice") or 0), kind="take_profit", label=f"{prefix} TP")
            _add(level=f"{prefix} SL", price=float(ev.get("slPrice") or 0), kind="stop_loss", label=f"{prefix} SL")
        elif act.startswith("EXIT_"):
            reason = str(ev.get("exitReason") or "EXIT")
            _add(
                level=f"Exit {reason}",
                price=float(ev.get("exitPrice") or ev.get("fillPrice") or 0),
                kind="exit",
                label=f"Exit {reason}",
            )
    return levels


def simulate_day(
    candles: list[dict[str, Any]],
    cfg: dict[str, Any],
    *,
    session_date: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    parsed = parse_strategy_config(cfg)
    rt = fresh_breakout_runtime(session_date=session_date)
    events: list[dict[str, Any]] = []
    day_report: dict[str, Any] = {
        "date": session_date,
        "referenceClose": 0.0,
        "referenceOpen": 0.0,
        "referenceHigh": 0.0,
        "referenceLow": 0.0,
        "referenceCandleTime": "",
        "buyTrigger": 0.0,
        "sellTrigger": 0.0,
        "buyTriggerFirstTouchTime": None,
        "sellTriggerFirstTouchTime": None,
        "buyTriggerTouchHigh": None,
        "sellTriggerTouchLow": None,
        "initialDirection": None,
        "initialTriggerTime": None,
        "firstTriggerSide": None,
        "result": "",
        "timeline": [],
        "roundTrips": [],
        "executionPolicy": EXECUTION_POLICY,
        "chartLevels": [],
        "sameBarNotes": [],
        "phase": "NO_TRADE",
        "pnl": 0.0,
    }

    ref_candle = find_reference_candle(candles, parsed["start_time"])
    if not ref_candle:
        rt["phase"] = "NO_TRADE"
        rt["message"] = f"No reference candle at {parsed['start_time']}"
        day_report["phase"] = "NO_TRADE"
        day_report["result"] = "No reference candle"
        day_report["timeline"] = build_timeline(
            start_time=parsed["start_time"],
            reference_close=0,
            ref_candle_time="",
            events=[],
            phase="NO_TRADE",
        )
        return rt, events, day_report

    rt = set_reference_from_candle(rt, ref_candle, parsed)
    ref_close = _num(rt.get("referencePrice"))
    buy_trig = _num(rt.get("buyTrigger"))
    sell_trig = _num(rt.get("sellTrigger"))
    ref_time = str(ref_candle.get("time") or "")

    day_report.update(
        {
            "referenceClose": ref_close,
            "referenceOpen": _num(ref_candle.get("open")),
            "referenceHigh": _num(ref_candle.get("high")),
            "referenceLow": _num(ref_candle.get("low")),
            "referenceCandleTime": ref_time,
            "buyTrigger": buy_trig,
            "sellTrigger": sell_trig,
        }
    )

    ref_hhmm = hhmm_from_candle_time(ref_time) or parsed["start_time"][:5]
    ref_seen = False

    for candle in candles:
        hhmm = hhmm_from_candle_time(str(candle.get("time") or ""))
        if hhmm == ref_hhmm:
            ref_seen = True
            continue
        if not ref_seen:
            continue
        if str(rt.get("phase")) in ("DONE", "NO_TRADE"):
            break

        if str(rt.get("phase")) == "WAIT_BREAKOUT":
            o, h, l, c = (
                _num(candle.get("open")),
                _num(candle.get("high")),
                _num(candle.get("low")),
                _num(candle.get("close")),
            )
            path = _bar_path(o, h, l, c)
            ct = str(candle.get("time") or "")
            if day_report["buyTriggerFirstTouchTime"] is None and h >= buy_trig - 1e-9:
                day_report["buyTriggerFirstTouchTime"] = ct
                day_report["buyTriggerTouchHigh"] = h
            if day_report["sellTriggerFirstTouchTime"] is None and l <= sell_trig + 1e-9:
                day_report["sellTriggerFirstTouchTime"] = ct
                day_report["sellTriggerTouchLow"] = l
            if _both_triggers_on_path(path, buy_trig, sell_trig):
                day_report["sameBarNotes"].append(
                    f"Both triggers touched on {format_time_label(ct)} — priority: {EXECUTION_POLICY['breakoutSameBarRule']}"
                )

        rt, actions = process_candle(cfg, rt, candle, after_reference=True)
        for act in actions:
            ev = {**act, "time": str(candle.get("time") or ""), "date": session_date}
            events.append(ev)
            if act.get("action", "").startswith("INITIAL_"):
                day_report["initialDirection"] = act.get("side")
                day_report["initialTriggerTime"] = ev["time"]
                day_report["firstTriggerSide"] = act.get("side")
            if act.get("sameBarAmbiguity"):
                day_report["sameBarNotes"].append(
                    f"Same-bar ambiguity on {format_time_label(ev['time'])} — {EXECUTION_POLICY['exitSameBarRule']}"
                )

    if str(rt.get("phase")) in ("IN_TRADE", "REVERSE_TRADE") and rt.get("side") in ("BUY", "SELL"):
        last_candle = candles[-1] if candles else None
        exit_px = _num(last_candle.get("close") if last_candle else rt.get("lastPrice"))
        if exit_px > 0:
            rt, eod_actions = _close_position(
                rt=rt,
                parsed=parsed,
                reason="EOD",
                exit_px=exit_px,
                allow_reverse=False,
            )
            for act in eod_actions:
                events.append({**act, "time": str(last_candle.get("time") if last_candle else ""), "date": session_date})

    if str(rt.get("phase")) == "WAIT_BREAKOUT":
        rt["phase"] = "NO_TRADE"
        rt["message"] = "No breakout before session end"
        day_report["result"] = "No breakout"

    round_trips = build_round_trip_trades(events)
    phase = str(rt.get("phase") or "NO_TRADE")
    if phase != "NO_TRADE" or round_trips:
        day_report["result"] = build_result_string(round_trips, phase if not round_trips else "DONE")

    day_report["roundTrips"] = round_trips
    day_report["phase"] = phase
    day_report["pnl"] = round(_num(rt.get("realizedPnl")), 2)
    day_report["timeline"] = build_timeline(
        start_time=parsed["start_time"],
        reference_close=ref_close,
        ref_candle_time=ref_time,
        events=events,
        phase=phase,
        reference_open=_num(day_report.get("referenceOpen")),
        reference_high=_num(day_report.get("referenceHigh")),
        reference_low=_num(day_report.get("referenceLow")),
        buy_trigger=buy_trig,
        sell_trigger=sell_trig,
        buy_trigger_touch_time=day_report.get("buyTriggerFirstTouchTime"),
        sell_trigger_touch_time=day_report.get("sellTriggerFirstTouchTime"),
        buy_trigger_touch_high=day_report.get("buyTriggerTouchHigh"),
        sell_trigger_touch_low=day_report.get("sellTriggerTouchLow"),
    )
    day_report["chartLevels"] = build_day_chart_levels(
        reference_close=ref_close,
        buy_trigger=buy_trig,
        sell_trigger=sell_trig,
        events=events,
    )

    if day_report["buyTriggerFirstTouchTime"] and day_report["sellTriggerFirstTouchTime"]:
        buy_t = day_report["buyTriggerFirstTouchTime"]
        sell_t = day_report["sellTriggerFirstTouchTime"]
        if buy_t == sell_t:
            day_report["firstTriggerSide"] = day_report.get("firstTriggerSide") or day_report.get("initialDirection")
        else:
            day_report["firstTriggerSide"] = "BUY" if str(buy_t) <= str(sell_t) else "SELL"

    return rt, events, day_report


def build_strategy_levels(cfg: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = parse_strategy_config(cfg)
    rt = runtime
    ref = _num(rt.get("referencePrice"))
    buy_trig = _num(rt.get("buyTrigger"))
    sell_trig = _num(rt.get("sellTrigger"))
    if ref <= 0:
        ref = _num(cfg.get("referencePrice"))
        if ref > 0:
            buy_trig, sell_trig = compute_triggers(ref, parsed["breakout_distance"])
    rows: list[dict[str, Any]] = []
    if ref > 0:
        rows.append({"level": "REF", "price": ref, "action": "Reference", "status": "set"})
    if buy_trig > 0:
        rows.append({"level": "BUY", "price": buy_trig, "action": "Buy trigger", "status": _trigger_status(rt, "BUY")})
    if sell_trig > 0:
        rows.append({"level": "SELL", "price": sell_trig, "action": "Sell trigger", "status": _trigger_status(rt, "SELL")})
    tp = _num(rt.get("tpPrice"))
    sl = _num(rt.get("slPrice"))
    if tp > 0:
        rows.append({"level": "TP", "price": tp, "action": "Take profit", "status": "active" if rt.get("positionLots") else "pending"})
    if sl > 0:
        rows.append({"level": "SL", "price": sl, "action": "Stop loss", "status": "active" if rt.get("positionLots") else "pending"})
    return rows


def _trigger_status(rt: dict[str, Any], side: str) -> str:
    phase = str(rt.get("phase") or "")
    if phase == "WAIT_BREAKOUT":
        return "armed"
    if phase in ("IN_TRADE", "REVERSE_TRADE", "DONE"):
        if rt.get("side") == side:
            return "filled"
        return "cancelled"
    return "pending"


def dashboard_snapshot_fields(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": str(runtime.get("phase") or "IDLE"),
        "reference_price": _num(runtime.get("referencePrice")),
        "buy_trigger": _num(runtime.get("buyTrigger")),
        "sell_trigger": _num(runtime.get("sellTrigger")),
        "side": runtime.get("side"),
        "entry_price": _num(runtime.get("entryPrice")),
        "tp_price": _num(runtime.get("tpPrice")),
        "sl_price": _num(runtime.get("slPrice")),
        "trade_count": _int(runtime.get("tradeCount")),
        "is_reverse": bool(runtime.get("isReverse")),
        "status_message": str(runtime.get("message") or ""),
        "ref_candle_time": str(runtime.get("refCandleTime") or ""),
        "session_date": str(runtime.get("sessionDate") or ""),
    }


def describe_breakout_next_action(
    *,
    phase: str,
    algo_running: bool,
    in_session: bool,
    reference_price: float,
    buy_trigger: float,
    sell_trigger: float,
    current_price: float,
    side: str | None,
    is_reverse: bool,
    entry_price: float,
    tp_price: float,
    sl_price: float,
    take_profit: float,
    stop_loss: float,
    lots: int,
    status_message: str,
) -> str:
    """Human next-action text for the dashboard only — does not affect trading."""
    if not algo_running:
        return "Algo stopped — Enable Algo to arm reference / breakout."
    if not in_session:
        return "Outside session window — ticks ignored until start–end time."
    phase_u = (phase or "IDLE").upper()
    if phase_u in ("IDLE", "WAIT_REF"):
        return status_message or "Waiting for start-time candle close as reference."
    if phase_u == "WAIT_BREAKOUT":
        if reference_price <= 0:
            return "Reference not set yet — waiting for start-time close."
        parts = [
            f"Armed on close/LTP {current_price:.2f} vs ref {reference_price:.2f}.",
            f"BUY if price >= {buy_trigger:.2f} -> TP +{take_profit:g} / SL -{stop_loss:g} ({lots} lot).",
            f"SELL if price <= {sell_trigger:.2f} -> TP -{take_profit:g} / SL +{stop_loss:g} ({lots} lot).",
        ]
        if current_price > 0 and buy_trigger > 0:
            parts.append(f"gap to BUY {buy_trigger - current_price:+.2f}")
        if current_price > 0 and sell_trigger > 0:
            parts.append(f"gap to SELL {current_price - sell_trigger:+.2f}")
        return " · ".join(parts)
    if phase_u in ("IN_TRADE", "REVERSE_TRADE"):
        kind = "Reverse" if is_reverse or phase_u == "REVERSE_TRADE" else "Initial"
        side_lbl = side or "—"
        return (
            f"{kind} {side_lbl} open @ {entry_price:.2f} · "
            f"exit TP {tp_price:.2f} / SL {sl_price:.2f}"
            + (" · reverse only if initial SL hits" if not is_reverse and phase_u == "IN_TRADE" else "")
        )
    if phase_u == "DONE":
        return status_message or "Session complete — no more entries today."
    if phase_u == "NO_TRADE":
        return status_message or "No breakout today."
    return status_message or phase_u


def process_price_tick(cfg: dict[str, Any], runtime: dict[str, Any], price: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Live LTP tick — detect breakout / TP / SL crosses at market price."""
    parsed = parse_strategy_config(cfg)
    rt = deepcopy(runtime)
    actions: list[dict[str, Any]] = []
    if price <= 0:
        return rt, actions

    prev = _num(rt.get("prevPrice"))
    if prev <= 0:
        prev = _num(rt.get("lastPrice")) or price
    rt["prevPrice"] = round(price, 4)
    rt["lastPrice"] = round(price, 4)
    phase = str(rt.get("phase") or "IDLE")

    if phase in ("DONE", "NO_TRADE"):
        return rt, actions

    if phase == "WAIT_BREAKOUT":
        buy_trig = _num(rt.get("buyTrigger"))
        sell_trig = _num(rt.get("sellTrigger"))
        side: Side | None = None
        # Decide strictly on the CURRENT price: BUY only at/above the buy trigger,
        # SELL only at/below the sell trigger. These are mutually exclusive
        # (buy trigger > sell trigger), so a falling price at the sell level can
        # never open a BUY — direction is always correct.
        if buy_trig > 0 and sell_trig > 0:
            if price >= buy_trig - 1e-9:
                side = "BUY"
            elif price <= sell_trig + 1e-9:
                side = "SELL"
        if side:
            rt, entry_action = _open_entry(side=side, fill=round(price, 4), parsed=parsed, rt=rt, is_reverse=False)
            actions.append(entry_action)
            # Entry done on this tick — TP/SL evaluation starts from the next tick
            # so the same tick's price span can never instantly stop out the entry.
            return rt, actions
        rt["message"] = (
            f"Armed · LTP {price:.2f} · Buy {buy_trig:.2f} (gap {buy_trig - price:+.2f}) · "
            f"Sell {sell_trig:.2f} (gap {price - sell_trig:+.2f})"
        )

    if phase in ("IN_TRADE", "REVERSE_TRADE") and rt.get("side") in ("BUY", "SELL"):
        side = rt["side"]  # type: Side
        tp = _num(rt.get("tpPrice"))
        sl = _num(rt.get("slPrice"))
        exit_reason: str | None = None
        # Exit strictly on the CURRENT price (no stale prev-price span):
        # BUY  → SL when price <= SL, TP when price >= TP.
        # SELL → SL when price >= SL, TP when price <= TP.
        if side == "BUY":
            if sl > 0 and price <= sl + 1e-9:
                exit_reason = "SL"
            elif tp > 0 and price >= tp - 1e-9:
                exit_reason = "TP"
        else:
            if sl > 0 and price >= sl - 1e-9:
                exit_reason = "SL"
            elif tp > 0 and price <= tp + 1e-9:
                exit_reason = "TP"
        if exit_reason:
            allow_rev = exit_reason == "SL" and phase == "IN_TRADE"
            rt, exit_actions = _close_position(
                rt=rt,
                parsed=parsed,
                reason=exit_reason,
                exit_px=round(price, 4),
                allow_reverse=allow_rev,
            )
            actions.extend(exit_actions)

    return rt, actions
