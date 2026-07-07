"""Strategy 3 — SENSEX Expiry Day ITM Premium Breakout (pure logic)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

Side = Literal["CE", "PE"]
ExitReason = Literal[
    "TP", "SL", "MANUAL", "EOD", "NO_TRADE", "PENDING",
    "TARGET_HIT", "STOPLOSS_HIT", "MARKET_CLOSE", "MARKET_CLOSE_EXIT", "PENDING_ENTRY",
    "TOKEN_NOT_FOUND", "DATA_ERROR", "WAITING",
]

# Premium close → entry add-on percentage (spec table)
PREMIUM_ENTRY_TIERS: list[tuple[float, float, float]] = [
    (0.0, 25.0, 0.65),
    (25.0, 35.0, 0.55),
    (35.0, 50.0, 0.45),
    (50.0, 75.0, 0.35),
    (75.0, 100.0, 0.30),
    (100.0, 125.0, 0.22),
]


@dataclass
class WindowConfig:
    index: int
    start_hhmm: str  # "14:35"


@dataclass
class OptionSetup:
    side: Side
    strike: float
    premium_close: float
    entry_pct: float | None
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    tradable: bool
    skip_reason: str | None = None


@dataclass
class CandleBar:
    time: str
    open: float
    high: float
    low: float
    close: float


def parse_hhmm(value: str) -> tuple[int, int]:
    parts = (value or "14:35").strip().split(":")
    hh = int(parts[0]) if parts else 14
    mm = int(parts[1]) if len(parts) > 1 else 35
    return hh, mm


def add_minutes_to_hhmm(hhmm: str, minutes: int) -> str:
    hh, mm = parse_hhmm(hhmm)
    total = hh * 60 + mm + minutes
    return f"{total // 60:02d}:{total % 60:02d}"


def build_trade_windows(first_start: str, count: int = 3, gap_minutes: int = 10) -> list[WindowConfig]:
    out: list[WindowConfig] = []
    for i in range(max(1, count)):
        out.append(WindowConfig(index=i, start_hhmm=add_minutes_to_hhmm(first_start, i * gap_minutes)))
    return out


def nearest_itm_ce_strike(reference: float) -> float:
    """ITM call: highest strike below reference (100-point ladder)."""
    step = 100.0
    return math.floor(reference / step) * step


def nearest_itm_pe_strike(reference: float) -> float:
    """ITM put: lowest strike above reference (100-point ladder)."""
    step = 100.0
    return math.ceil(reference / step) * step


def intrinsic_value(side: Side, strike: float, reference_close: float) -> float:
    """ITM intrinsic value in index points."""
    if side == "CE":
        return max(0.0, reference_close - strike)
    return max(0.0, strike - reference_close)


def validate_expiry_session_premium(
    side: Side,
    strike: float,
    reference_close: float,
    premium_close: float,
    *,
    cfg: dict[str, Any] | None = None,
) -> str | None:
    """
    Return error message if premium is inconsistent with ITM intrinsic on expiry session.
    Catches wrong contract / wrong candle (e.g. 500+ when intrinsic is ~40).
    """
    if premium_close <= 0:
        return "Option premium missing or zero for reference candle"
    intrinsic = intrinsic_value(side, strike, reference_close)
    max_tier = max_tradable_premium(cfg)
    # On expiry afternoon, premium should not exceed intrinsic + max tradable tier by much.
    ceiling = intrinsic + max_tier + 15.0
    if premium_close > ceiling:
        return (
            f"Premium {premium_close:.2f} inconsistent with intrinsic {intrinsic:.2f} "
            f"(max plausible ~{ceiling:.0f}) — wrong contract or candle"
        )
    # Keep the low-side guard lenient. StocksRin expiry snapshots can occasionally
    # print well below intrinsic, but those rows are still usable for the strategy's
    # premium-tier filters. The high-side check is the main protection against
    # accidentally pulling the wrong expiry/contract.
    floor = max(0.0, intrinsic - (max_tier + 15.0))
    if premium_close < floor:
        return (
            f"Premium {premium_close:.2f} below intrinsic {intrinsic:.2f} — wrong contract or candle"
        )
    return None


def default_premium_tiers() -> list[dict[str, Any]]:
    return [
        {"maxPremium": 25, "entryPercent": 65},
        {"maxPremium": 35, "entryPercent": 55},
        {"maxPremium": 50, "entryPercent": 45},
        {"maxPremium": 75, "entryPercent": 35},
        {"maxPremium": 100, "entryPercent": 30},
        {"maxPremium": 125, "entryPercent": 22},
    ]


def tiers_from_config(cfg: dict[str, Any] | None) -> list[tuple[float, float, float]]:
    """Convert config premiumTiers to (lo, hi, decimal_pct) tuples."""
    raw = (cfg or {}).get("premiumTiers")
    if not isinstance(raw, list) or not raw:
        raw = default_premium_tiers()
    out: list[tuple[float, float, float]] = []
    lo = 0.0
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            hi = float(row.get("maxPremium") or 0)
            pct_ui = float(row.get("entryPercent") or 0)
        except (TypeError, ValueError):
            continue
        if hi <= lo:
            continue
        out.append((lo, hi, pct_ui / 100.0))
        lo = hi
    if not out:
        for lo, hi, pct in PREMIUM_ENTRY_TIERS:
            out.append((lo, hi, pct))
    return out


def max_tradable_premium(cfg: dict[str, Any] | None) -> float:
    tiers = tiers_from_config(cfg)
    return tiers[-1][1] if tiers else 125.0


def entry_percentage_for_premium(
    premium_close: float,
    cfg: dict[str, Any] | None = None,
) -> float | None:
    max_prem = max_tradable_premium(cfg)
    if premium_close <= 0 or premium_close > max_prem:
        return None
    tiers = tiers_from_config(cfg)
    for lo, hi, pct in tiers:
        if premium_close <= hi:
            if lo == 0 or premium_close > lo:
                return pct
    return None


def calc_entry_price(premium_close: float, entry_pct: float) -> float:
    return round(premium_close * (1.0 + entry_pct), 2)


def calc_target_price(entry_price: float, target_pct: float) -> float:
    return round(entry_price * (1.0 + target_pct / 100.0), 2)


def calc_stop_price(entry_price: float, stop_pct: float) -> float:
    return round(entry_price * (1.0 - stop_pct / 100.0), 2)


def evaluate_option_setup(
    *,
    side: Side,
    strike: float,
    premium_close: float,
    target_pct: float,
    stop_pct: float,
    cfg: dict[str, Any] | None = None,
) -> OptionSetup:
    pct = entry_percentage_for_premium(premium_close, cfg)
    max_prem = max_tradable_premium(cfg)
    if pct is None:
        reason = f"Premium > {max_prem:g}" if premium_close > max_prem else "Premium not eligible"
        return OptionSetup(
            side=side,
            strike=strike,
            premium_close=premium_close,
            entry_pct=None,
            entry_price=None,
            target_price=None,
            stop_price=None,
            tradable=False,
            skip_reason=reason,
        )
    entry = calc_entry_price(premium_close, pct)
    return OptionSetup(
        side=side,
        strike=strike,
        premium_close=premium_close,
        entry_pct=pct,
        entry_price=entry,
        target_price=calc_target_price(entry, target_pct),
        stop_price=calc_stop_price(entry, stop_pct),
        tradable=True,
    )


def evaluate_window_setups(
    reference_close: float,
    ce_premium_close: float,
    pe_premium_close: float,
    *,
    target_pct: float,
    stop_pct: float,
    cfg: dict[str, Any] | None = None,
) -> tuple[OptionSetup, OptionSetup]:
    ce_strike = nearest_itm_ce_strike(reference_close)
    pe_strike = nearest_itm_pe_strike(reference_close)
    ce = evaluate_option_setup(
        side="CE", strike=ce_strike, premium_close=ce_premium_close,
        target_pct=target_pct, stop_pct=stop_pct, cfg=cfg,
    )
    pe = evaluate_option_setup(
        side="PE", strike=pe_strike, premium_close=pe_premium_close,
        target_pct=target_pct, stop_pct=stop_pct, cfg=cfg,
    )
    return ce, pe


def _bar_time_contains(bar_time: str, hhmm: str) -> bool:
    """True if candle timestamp contains the window start HH:MM."""
    t = (bar_time or "").replace("T", " ")
    return hhmm in t


def _bar_datetime(bar: CandleBar):
    from datetime import datetime

    return datetime.fromisoformat(bar.time.replace("Z", "+00:00"))


def _median_bar_gap_seconds(bars: list[CandleBar], sample: int = 8) -> float | None:
    if len(bars) < 2:
        return None
    n = min(len(bars) - 1, sample)
    gaps = []
    for i in range(1, n + 1):
        gaps.append(_bar_datetime(bars[i]).timestamp() - _bar_datetime(bars[i - 1]).timestamp())
    gaps.sort()
    return gaps[len(gaps) // 2]


def resample_bars(
    bars: list[CandleBar],
    minutes: int,
    *,
    session_open_hhmm: str = "09:15",
) -> list[CandleBar]:
    """
    Aggregate finer candles (e.g. 1m from StocksRin) into N-minute OHLC bars
    aligned to the cash session open (09:15 IST).
    """
    if not bars or minutes <= 1:
        return bars
    gap = _median_bar_gap_seconds(bars)
    if gap is not None and gap >= minutes * 60 * 0.75:
        return bars

    open_hh, open_mm = parse_hhmm(session_open_hhmm)
    open_mins = open_hh * 60 + open_mm
    buckets: dict[int, list[CandleBar]] = {}
    for bar in bars:
        dt = _bar_datetime(bar)
        total = dt.hour * 60 + dt.minute
        if total < open_mins:
            continue
        offset = total - open_mins
        bucket_mins = open_mins + (offset // minutes) * minutes
        buckets.setdefault(bucket_mins, []).append(bar)

    out: list[CandleBar] = []
    for bucket_mins in sorted(buckets):
        chunk = buckets[bucket_mins]
        if not chunk:
            continue
        bh, bm = bucket_mins // 60, bucket_mins % 60
        dt0 = _bar_datetime(chunk[0])
        label = dt0.replace(hour=bh, minute=bm, second=0, microsecond=0).isoformat(timespec="seconds")
        out.append(
            CandleBar(
                time=label,
                open=chunk[0].open,
                high=max(b.high for b in chunk),
                low=min(b.low for b in chunk),
                close=chunk[-1].close,
            )
        )
    return out


def _bar_clock(bar_time: str) -> str:
    t = (bar_time or "").replace("T", " ")
    return t[11:16] if len(t) >= 16 else t[:5]


def find_window_reference_bar(
    bars: list[CandleBar],
    start_hhmm: str,
    *,
    window_minutes: int = 10,
) -> CandleBar | None:
    """
    Closed reference candle for the window (e.g. 14:35 → 14:35–14:45 bar).
    Only the bar whose open label matches the window start is used.
    """
    needle = start_hhmm.strip()
    for bar in bars:
        if _bar_clock(bar.time) == needle:
            return bar
    for bar in bars:
        if _bar_time_contains(bar.time, needle):
            return bar
    return None


def reference_candle_end_hhmm(start_hhmm: str, window_minutes: int = 10) -> str:
    return add_minutes_to_hhmm(start_hhmm, window_minutes)


def find_bar_by_time(bars: list[CandleBar], ref_time: str) -> int | None:
    """Index of bar matching reference timestamp exactly."""
    for i, bar in enumerate(bars):
        if bar.time == ref_time:
            return i
    ref_norm = ref_time.replace("T", " ")
    for i, bar in enumerate(bars):
        if ref_norm in bar.time.replace("T", " "):
            return i
    return None


def _fill_price_buy_stop(bar: CandleBar, entry_price: float) -> float | None:
    """Buy-stop fill when high reaches entry; gap opens fill at open."""
    if bar.high < entry_price:
        return None
    if bar.open >= entry_price:
        return round(bar.open, 2)
    return entry_price


def _bar_hits_tp_sl(bar: CandleBar, tp: float | None, sl: float | None) -> tuple[bool, bool]:
    tp_hit = tp is not None and bar.high >= tp
    sl_hit = sl is not None and bar.low <= sl
    return tp_hit, sl_hit


def _resolve_ambiguous_exit(
    entry_price: float,
    tp: float | None,
    sl: float | None,
    policy: str,
) -> dict[str, Any]:
    best_pnl = round((tp - entry_price), 2) if tp is not None else 0.0
    worst_pnl = round((sl - entry_price), 2) if sl is not None else 0.0
    pol = (policy or "conservative").lower()
    if pol == "optimistic":
        chosen_reason, chosen_price, pnl = "TARGET_HIT", tp, best_pnl
    elif pol == "mark":
        chosen_reason, chosen_price, pnl = "AMBIGUOUS", None, 0.0
    else:
        chosen_reason, chosen_price, pnl = "STOPLOSS_HIT", sl, worst_pnl
    return {
        "status": "AMBIGUOUS",
        "exit_reason": "AMBIGUOUS",
        "exit_price": chosen_price,
        "pnl": pnl,
        "points": pnl,
        "best_case_exit_reason": "TARGET_HIT",
        "best_case_exit_price": tp,
        "best_case_pnl": best_pnl,
        "worst_case_exit_reason": "STOPLOSS_HIT",
        "worst_case_exit_price": sl,
        "worst_case_pnl": worst_pnl,
        "resolved_as": chosen_reason if pol != "mark" else None,
        "ambiguous_policy": pol,
    }


def _same_bar_exit_long(
    bar: CandleBar,
    entry_price: float,
    tp: float | None,
    sl: float | None,
) -> tuple[str, float] | None | str:
    """
    After buy-stop entry on this bar, resolve TP/SL.
    Returns "AMBIGUOUS" if both levels touched on the same bar.
    """
    o, h, l, c = bar.open, bar.high, bar.low, bar.close
    if h < entry_price:
        return None

    tp_hit, sl_hit = _bar_hits_tp_sl(bar, tp, sl)
    if tp_hit and sl_hit:
        return "AMBIGUOUS"

    if c >= o:
        if tp_hit:
            return ("TARGET_HIT", tp)
        if sl_hit and o >= entry_price:
            return ("STOPLOSS_HIT", sl)
    else:
        if tp_hit:
            return ("TARGET_HIT", tp)
        if sl_hit:
            return ("STOPLOSS_HIT", sl)
    return None


def bars_from_monitor_start(bars: list[CandleBar], monitor_start_hhmm: str) -> list[CandleBar]:
    """1m (or fine) bars on/after reference candle close (e.g. 14:45)."""
    start = monitor_start_hhmm.strip()
    return [b for b in bars if _bar_clock(b.time) >= start]


def simulate_option_trade(
    bars: list[CandleBar],
    setup: OptionSetup,
    *,
    start_idx: int = 0,
    ambiguous_policy: str = "conservative",
    monitor_resolution_minutes: int = 1,
) -> dict[str, Any]:
    """
    Monitor phase (post reference close): buy-stop entry, then TP/SL.
    Prefer 1-minute bars (monitor_resolution_minutes=1) to avoid same-10m-bar ambiguity.
    When TP and SL both touch on the same bar → AMBIGUOUS (best/worst case recorded).
    """
    if not setup.tradable or setup.entry_price is None:
        return {
            "status": "NO_TRADE",
            "exit_reason": "NO_TRADE",
            "skip_reason": setup.skip_reason,
            "pnl": 0.0,
        }

    entry_price = setup.entry_price
    tp = setup.target_price
    sl = setup.stop_price
    filled = False
    fill_time: str | None = None
    fill_bar: CandleBar | None = None
    exit_time: str | None = None
    exit_bar: CandleBar | None = None
    exit_price: float | None = None
    exit_reason: str = "PENDING_ENTRY"
    highest_after_entry: float | None = None
    lowest_after_entry: float | None = None
    highest_during_monitoring: float | None = None

    monitor_bars = bars[start_idx:]
    for bar in monitor_bars:
        highest_during_monitoring = max(highest_during_monitoring or bar.high, bar.high)

        if not filled:
            fill = _fill_price_buy_stop(bar, entry_price)
            if fill is None:
                continue
            filled = True
            fill_time = bar.time
            fill_bar = bar
            highest_after_entry = bar.high
            lowest_after_entry = bar.low

            same = _same_bar_exit_long(bar, entry_price, tp, sl)
            if same == "AMBIGUOUS":
                amb = _resolve_ambiguous_exit(entry_price, tp, sl, ambiguous_policy)
                exit_reason = amb["exit_reason"]
                exit_price = amb["exit_price"]
                exit_time = bar.time
                exit_bar = bar
                filled = True
                fill_time = bar.time
                fill_bar = bar
                highest_after_entry = bar.high
                lowest_after_entry = bar.low
                break
            if same:
                exit_reason, exit_price = same
                exit_time = bar.time
                exit_bar = bar
                break
            continue

        highest_after_entry = max(highest_after_entry or bar.high, bar.high)
        lowest_after_entry = min(lowest_after_entry or bar.low, bar.low)

        tp_hit, sl_hit = _bar_hits_tp_sl(bar, tp, sl)
        if tp_hit and sl_hit:
            amb = _resolve_ambiguous_exit(entry_price, tp, sl, ambiguous_policy)
            exit_reason = amb["exit_reason"]
            exit_price = amb["exit_price"]
            exit_time = bar.time
            exit_bar = bar
            break
        if tp_hit:
            exit_price = tp
            exit_reason = "TARGET_HIT"
            exit_time = bar.time
            exit_bar = bar
            break
        if sl_hit:
            exit_price = sl
            exit_reason = "STOPLOSS_HIT"
            exit_time = bar.time
            exit_bar = bar
            break

    if not filled:
        return {
            "status": "PENDING_ENTRY",
            "exit_reason": "PENDING_ENTRY",
            "entry_price": entry_price,
            "trigger_price": entry_price,
            "pnl": 0.0,
            "points": 0.0,
            "highest_during_monitoring": round(highest_during_monitoring, 2) if highest_during_monitoring is not None else None,
            "monitor_candle_count": len(monitor_bars),
            "monitor_resolution_minutes": monitor_resolution_minutes,
        }

    if exit_reason == "AMBIGUOUS":
        amb = _resolve_ambiguous_exit(entry_price, tp, sl, ambiguous_policy)
        duration_min = _duration_minutes(fill_time, exit_time)
        return {
            **amb,
            "entry_price": entry_price,
            "entry_premium": entry_price,
            "fill_time": fill_time,
            "exit_time": exit_time,
            "fill_bar": fill_bar,
            "exit_bar": exit_bar,
            "trigger_candle_high": round(fill_bar.high, 2) if fill_bar else None,
            "trigger_candle_low": round(fill_bar.low, 2) if fill_bar else None,
            "target_price": tp,
            "stop_price": sl,
            "trade_duration_minutes": duration_min,
            "highest_after_entry": round(highest_after_entry, 2) if highest_after_entry is not None else None,
            "lowest_after_entry": round(lowest_after_entry, 2) if lowest_after_entry is not None else None,
            "highest_during_monitoring": round(highest_during_monitoring, 2) if highest_during_monitoring is not None else None,
            "monitor_candle_count": len(monitor_bars),
            "monitor_resolution_minutes": monitor_resolution_minutes,
            "same_bar_tp_sl_conflict": True,
        }

    if exit_price is None:
        last = bars[-1] if bars else None
        exit_price = round(last.close, 2) if last else entry_price
        exit_reason = "MARKET_CLOSE"
        exit_time = last.time if last else fill_time
        exit_bar = last

    pnl = round((exit_price - entry_price), 2)
    duration_min = _duration_minutes(fill_time, exit_time)
    return {
        "status": exit_reason,
        "exit_reason": exit_reason,
        "entry_price": entry_price,
        "entry_premium": entry_price,
        "exit_price": exit_price,
        "last_candle_close": round(exit_bar.close, 2) if exit_bar and exit_reason == "MARKET_CLOSE" else None,
        "fill_time": fill_time,
        "exit_time": exit_time,
        "fill_bar": fill_bar,
        "exit_bar": exit_bar,
        "trigger_candle_high": round(fill_bar.high, 2) if fill_bar else None,
        "trigger_candle_low": round(fill_bar.low, 2) if fill_bar else None,
        "pnl": pnl,
        "points": pnl,
        "target_price": tp,
        "stop_price": sl,
        "trade_duration_minutes": duration_min,
        "highest_after_entry": round(highest_after_entry, 2) if highest_after_entry is not None else None,
        "lowest_after_entry": round(lowest_after_entry, 2) if lowest_after_entry is not None else None,
        "highest_during_monitoring": round(highest_during_monitoring, 2) if highest_during_monitoring is not None else None,
        "monitor_candle_count": len(monitor_bars),
        "monitor_resolution_minutes": monitor_resolution_minutes,
        "same_bar_tp_sl_conflict": False,
    }


def _duration_minutes(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, int((b - a).total_seconds() // 60))
    except ValueError:
        return None


def default_config() -> dict[str, Any]:
    return {
        "startTime": "14:35",
        "windowCount": 3,
        "windowGapMinutes": 10,
        "candleTimeframeMinutes": 10,
        "targetPercent": 25.0,
        "stopLossPercent": 30.0,
        "quantity": 1,
        "productType": "MIS",
        "expiryDayOnly": True,
        "premiumTiers": default_premium_tiers(),
        # independent = each window fresh (historical analysis)
        # sequential = skip window if prior trade still open at this window ref close
        "windowExecutionMode": "independent",
        "oneTradeAtATime": False,
        # conservative = SL on ambiguous same-bar TP+SL; optimistic = TP; mark = AMBIGUOUS pnl 0
        "ambiguousExitPolicy": "conservative",
    }


def parse_config(cfg: dict[str, Any]) -> dict[str, Any]:
    d = default_config()
    d.update({k: v for k, v in (cfg or {}).items() if v is not None})
    d["targetPercent"] = float(d.get("targetPercent") or 25)
    d["stopLossPercent"] = float(d.get("stopLossPercent") or 30)
    d["quantity"] = max(1, int(d.get("quantity") or 1))
    d["windowCount"] = max(1, min(5, int(d.get("windowCount") or 3)))
    d["windowGapMinutes"] = max(5, int(d.get("windowGapMinutes") or 10))
    tiers = d.get("premiumTiers")
    if not isinstance(tiers, list) or not tiers:
        d["premiumTiers"] = default_premium_tiers()
    d.pop("expiryWeekday", None)
    return d


def is_expiry_session_day(date_str: str, cfg: dict[str, Any] | None) -> bool:
    """True if date is the auto-detected SENSEX weekly expiry session."""
    parsed = parse_config(cfg or {})
    if not parsed.get("expiryDayOnly", True):
        return True
    from app.services.sensex_expiry import is_sensex_expiry_date

    return is_sensex_expiry_date(date_str)
