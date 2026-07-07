"""OHLC candle processing helpers for grid backtest (1-min bars, no tick data)."""

from __future__ import annotations

from typing import Any

from app.services.grid_logic import (
    build_grid_levels,
    expand_grid_traversal_path,
    grid_level_prices,
    parse_strategy_config,
    process_price_tick,
)


def _dedupe_prices(prices: list[float]) -> list[float]:
    out: list[float] = []
    for px in prices:
        if px <= 0:
            continue
        if not out or abs(px - out[-1]) > 1e-9:
            out.append(px)
    return out


def _grid_prices(cfg: dict[str, Any]) -> list[float]:
    parsed = parse_strategy_config(cfg)
    levels = build_grid_levels(
        reference_price=parsed["reference_price"],
        grid_gap=parsed["grid_gap"],
        levels_above=parsed["grid_levels_above"],
        levels_below=parsed["grid_levels_below"],
        initial_lots=parsed["initial_lots"],
        lots_per_grid=parsed["lots_per_grid"],
        invert_grid=parsed["invert_grid"],
    )
    return grid_level_prices(levels)


def _expand_with_grid_waypoints(prices: list[float], grid_prices: list[float]) -> list[float]:
    return expand_grid_traversal_path(prices, grid_prices)


def _intrabar_prices(
    *,
    open_price: float,
    close_price: float,
    high_price: float | None,
    low_price: float | None,
    skip_open_segment: bool,
) -> list[float]:
    o = open_price
    c = close_price
    h = high_price if high_price and high_price > 0 else max(o, c)
    l = low_price if low_price and low_price > 0 else min(o, c)

    if skip_open_segment:
        if c >= o:
            return _dedupe_prices([h, c])
        return _dedupe_prices([l, c])

    if c >= o:
        return _dedupe_prices([o, h, c])
    return _dedupe_prices([o, l, c])


def process_backtest_candle(
    cfg: dict[str, Any],
    runtime: dict[str, Any],
    *,
    open_price: float,
    close_price: float,
    high_price: float | None = None,
    low_price: float | None = None,
    skip_open_segment: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Process one 1-minute OHLC candle with conservative intrabar rules.

    - Uses open -> high/low -> close, expanding every grid level in between.
    - At most one grid action per level per candle.
    """
    level_lock: set[str] = set()
    actions: list[dict[str, Any]] = []

    raw_path = _intrabar_prices(
        open_price=open_price,
        close_price=close_price,
        high_price=high_price,
        low_price=low_price,
        skip_open_segment=skip_open_segment,
    )

    if not raw_path and close_price > 0:
        raw_path = [close_price]

    prev_px = float(runtime.get("lastPrice") or runtime.get("prevPrice") or 0)
    if prev_px > 0 and raw_path and abs(prev_px - raw_path[0]) > 1e-9:
        raw_path = [prev_px, *raw_path]

    grid_prices = _grid_prices(cfg)
    prices = _expand_with_grid_waypoints(raw_path, grid_prices)

    for px in prices:
        runtime, acts = _tick_with_level_lock(cfg, runtime, px, level_lock)
        actions.extend(acts)

    if not prices and close_price > 0 and open_price == close_price and not skip_open_segment:
        runtime["prevPrice"] = close_price
        runtime["lastPrice"] = close_price

    return runtime, actions


def _tick_with_level_lock(
    cfg: dict[str, Any],
    runtime: dict[str, Any],
    price: float,
    level_lock: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tick_cfg = {**cfg, "grid_runtime": runtime}
    runtime, raw_actions = process_price_tick(tick_cfg, runtime, price)

    kept: list[dict[str, Any]] = []
    for act in raw_actions:
        level_id = str(act.get("level") or "")
        if not level_id:
            continue
        unwind_d = act.get("unwindD")
        reenter_u = act.get("reenterU")
        lock_key = (
            f"{level_id}:unwind:{unwind_d}"
            if unwind_d
            else f"{level_id}:reenter:{reenter_u}"
            if reenter_u
            else level_id
        )
        if lock_key in level_lock:
            continue
        level_lock.add(lock_key)
        kept.append(act)
    return runtime, kept
