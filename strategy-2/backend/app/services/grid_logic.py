"""Build grid levels and process price ticks for Strategy 2 MCX grid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal


LevelKind = Literal["upper", "base", "lower"]
CrossDir = Literal["up", "down"]
LevelPhase = Literal["neutral", "sold", "added"]


@dataclass(frozen=True)
class GridLevel:
    level_id: str
    price: float
    action_label: str
    kind: LevelKind


def _num(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else default
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _month_from_as_of(as_of: date | datetime | str | None) -> int | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.month
    if isinstance(as_of, date):
        return as_of.month
    text = str(as_of).strip()
    if len(text) >= 7 and text[4] == "-":
        try:
            return int(text[5:7])
        except ValueError:
            return None
    return None


def _month_year_from_as_of(as_of: date | datetime | str | None) -> tuple[int, int] | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.month, as_of.year
    if isinstance(as_of, date):
        return as_of.month, as_of.year
    text = str(as_of).strip()[:10]
    if len(text) == 10 and text[4] == "-":
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
            return dt.month, dt.year
        except ValueError:
            return None
    return None


def _month_year_from_expiry_iso(expiry: str) -> tuple[int, int] | None:
    text = (expiry or "").strip()[:10]
    if len(text) != 10 or text[4] != "-":
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
        return dt.month, dt.year
    except ValueError:
        return None


def resolve_invert_grid(cfg: dict[str, Any], *, as_of: date | datetime | str | None = None) -> bool:
    """Buy-side expiry month: normal buy grid (opposite OFF). Sell-side expiry month: short grid (opposite ON)."""
    my = _month_year_from_as_of(as_of)
    if my is not None:
        buy_my = _month_year_from_expiry_iso(str(cfg.get("buySideExpiry") or ""))
        sell_my = _month_year_from_expiry_iso(str(cfg.get("sellSideExpiry") or ""))
        if buy_my and my == buy_my:
            return False
        if sell_my and my == sell_my:
            return True
        buy_month = _int(cfg.get("buySideMonth"), 0)
        sell_month = _int(cfg.get("sellSideMonth"), 0)
        if buy_month > 0 and my[0] == buy_month:
            return False
        if sell_month > 0 and my[0] == sell_month:
            return True
    invert_raw = cfg.get("invertGrid")
    return invert_raw is True or str(invert_raw).lower() in ("1", "true", "yes")


def resolve_active_expiry(cfg: dict[str, Any], *, as_of: date | datetime | str | None = None) -> str:
    if resolve_invert_grid(cfg, as_of=as_of):
        return str(cfg.get("sellSideExpiry") or "").strip()[:10]
    return str(cfg.get("buySideExpiry") or "").strip()[:10]


def config_with_invert_for_date(cfg: dict[str, Any], as_of: date | datetime | str | None) -> dict[str, Any]:
    return {**cfg, "invertGrid": resolve_invert_grid(cfg, as_of=as_of)}


def _exit_side_levels_needed(initial_lots: int, lots_per_grid: int) -> int:
    """Exit-side grid levels required for the full inventory to reach zero lots."""
    if initial_lots <= 0 or lots_per_grid <= 0:
        return 0
    return -(-initial_lots // lots_per_grid)  # ceil division


def parse_strategy_config(cfg: dict[str, Any], *, as_of: date | datetime | str | None = None) -> dict[str, Any]:
    invert_grid = resolve_invert_grid(cfg, as_of=as_of)
    initial_lots = _int(cfg.get("initialLots"))
    lots_per_grid = max(0, _int(cfg.get("lotsPerGrid")))
    levels_above = max(0, _int(cfg.get("gridLevelsAbove")))
    levels_below = max(0, _int(cfg.get("gridLevelsBelow")))
    # Exit side keeps extending beyond the configured level count until every lot
    # can exit (grid switches off only at 0 lots). The add side stays capped at
    # the configured setting (no adds beyond gridLevelsBelow / gridLevelsAbove).
    exit_levels = _exit_side_levels_needed(initial_lots, lots_per_grid)
    if invert_grid:
        levels_below = max(levels_below, exit_levels)
    else:
        levels_above = max(levels_above, exit_levels)
    return {
        "start_time": str(cfg.get("startTime") or "09:00"),
        "end_time": str(cfg.get("endTime") or "23:30"),
        "market": str(cfg.get("market") or "CRUDE_OIL").upper(),
        "reference_price": _num(cfg.get("referencePrice")),
        "initial_lots": initial_lots,
        "grid_gap": _num(cfg.get("gridGap")),
        "grid_levels_above": levels_above,
        "grid_levels_below": levels_below,
        "lots_per_grid": lots_per_grid,
        "invert_grid": invert_grid,
    }


def build_grid_levels(
    *,
    reference_price: float,
    grid_gap: float,
    levels_above: int,
    levels_below: int,
    initial_lots: int,
    lots_per_grid: int,
    invert_grid: bool = False,
) -> list[GridLevel]:
    if reference_price <= 0 or grid_gap <= 0:
        return []

    upper_label = (
        f"Up Buy {lots_per_grid} / Down Exit"
        if invert_grid
        else f"Up Exit / Down Buy {lots_per_grid}"
    )
    lower_label = (
        f"Up Exit / Down Add {lots_per_grid}"
        if invert_grid
        else f"Down Add / Base Exit {lots_per_grid}"
    )

    levels: list[GridLevel] = []
    for i in range(levels_above, 0, -1):
        levels.append(
            GridLevel(
                level_id=f"U{i}",
                price=round(reference_price + i * grid_gap, 4),
                action_label=upper_label,
                kind="upper",
            )
        )
    levels.append(
        GridLevel(
            level_id="BASE",
            price=round(reference_price, 4),
            action_label=f"Initial Buy {initial_lots} Lots",
            kind="base",
        )
    )
    for i in range(1, levels_below + 1):
        levels.append(
            GridLevel(
                level_id=f"D{i}",
                price=round(reference_price - i * grid_gap, 4),
                action_label=lower_label,
                kind="lower",
            )
        )
    return sorted(levels, key=lambda x: x.price, reverse=True)


def default_runtime() -> dict[str, Any]:
    return {
        "positionLots": 0,
        "realizedPnl": 0.0,
        "avgEntryPrice": 0.0,
        "lastPrice": 0.0,
        "prevPrice": 0.0,
        "sessionAnchorPrice": 0.0,
        "sessionReferencePrice": 0.0,
        "lastLevelId": None,
        "baseEntered": False,
        "levelStates": {},
        "upperArmLocks": {},
        "upperReenterHold": {},
        "upperPeakSold": 0,
        "nextActionLevel": None,
        "effectiveInvertGrid": None,
    }


def session_reference_price(cfg: dict[str, Any], runtime: dict[str, Any] | None = None) -> float:
    """Grid mid-price: frozen only after BASE/position is live; otherwise follow settings."""
    rt = runtime if isinstance(runtime, dict) else load_runtime(cfg)
    settings_ref = _num(cfg.get("referencePrice"))
    in_trade = int(rt.get("positionLots") or 0) > 0 or bool(rt.get("baseEntered"))
    if in_trade:
        frozen = _num(rt.get("sessionReferencePrice"))
        if frozen > 0:
            return frozen
    return settings_ref


def load_runtime(cfg: dict[str, Any]) -> dict[str, Any]:
    rt = cfg.get("grid_runtime")
    base = default_runtime()
    if isinstance(rt, dict):
        base.update(rt)
    if not isinstance(base.get("levelStates"), dict):
        base["levelStates"] = {}
    if not isinstance(base.get("upperArmLocks"), dict):
        base["upperArmLocks"] = {}
    if not isinstance(base.get("upperReenterHold"), dict):
        base["upperReenterHold"] = {}
    return base


def _level_phase(states: dict[str, Any], level_id: str) -> LevelPhase:
    raw = states.get(level_id, "neutral")
    if raw in ("neutral", "sold", "added"):
        return raw
    return "neutral"


def _upper_idx(level_id: str) -> int:
    return int(level_id[1:]) if level_id.startswith("U") and level_id[1:].isdigit() else 0


def _lower_idx(level_id: str) -> int:
    return int(level_id[1:]) if level_id.startswith("D") and level_id[1:].isdigit() else 0


def _deepest_added_d(level_states: dict[str, str], max_lower: int = 3) -> str | None:
    for n in range(max_lower, 0, -1):
        if _level_phase(level_states, f"D{n}") == "added":
            return f"D{n}"
    return None


def _count_sold_upper(level_states: dict[str, str], max_upper: int) -> int:
    return sum(1 for i in range(1, max_upper + 1) if _level_phase(level_states, f"U{i}") == "sold")


def _count_sold_lower(level_states: dict[str, str], max_lower: int) -> int:
    return sum(1 for i in range(1, max_lower + 1) if _level_phase(level_states, f"D{i}") == "sold")


def _absolute_inventory_floor(initial_lots: int, exit_side_levels: int, lots_per_grid: int) -> int:
    """Lowest position allowed after all exit-side grid levels have sold.

    Exit side extends until every lot can leave, so this is normally 0
    (grid switches off only when lots reach zero).
    """
    return max(0, initial_lots - exit_side_levels * lots_per_grid)


def _protected_inventory_floor(
    initial_lots: int,
    level_states: dict[str, str],
    exit_side_levels: int,
    lots_per_grid: int,
    *,
    invert_grid: bool = False,
) -> int:
    """Position that must be preserved while current exit-side legs remain sold (before adds)."""
    if invert_grid:
        sold = _count_sold_lower(level_states, exit_side_levels)
    else:
        sold = _count_sold_upper(level_states, exit_side_levels)
    return max(0, initial_lots - sold * lots_per_grid)


def _max_exit_qty(
    *,
    position_lots: int,
    lots_per_grid: int,
    floor_lots: int,
) -> int:
    return max(0, min(lots_per_grid, position_lots - floor_lots))


def _d_added_lots(level_states: dict[str, str], max_lower: int, lots_per_grid: int) -> int:
    return _count_d_added(level_states, max_lower) * lots_per_grid


def _count_d_added(level_states: dict[str, str], max_lower: int) -> int:
    return sum(1 for i in range(1, max_lower + 1) if _level_phase(level_states, f"D{i}") == "added")


def grid_level_tolerance(grid_gap: float) -> float:
    """Small band for poll/touch when LTP is effectively at a grid level."""
    if grid_gap <= 0:
        return 0.05
    return min(0.12, max(0.05, grid_gap * 0.05))


def _touch_tolerance(grid_gap: float) -> float:
    return grid_level_tolerance(grid_gap)


def grid_order_price(level_px: float) -> float:
    """Broker/accounting price — always the grid level, never LTP."""
    return round(level_px, 2) if level_px > 0 else 0.0


def ltp_matches_grid_level(ltp: float, grid_price: float, grid_gap: float) -> bool:
    """True when live LTP is close enough to a grid trigger price to place an order."""
    if ltp <= 0 or grid_price <= 0:
        return False
    return abs(ltp - grid_price) <= grid_level_tolerance(grid_gap)


def _allow_base_touch_entry(
    session_anchor: float,
    base_price: float,
    current_price: float,
    grid_gap: float,
) -> bool:
    """Touch entry only when LTP reaches BASE from the session approach side."""
    tol = _touch_tolerance(grid_gap)
    if abs(current_price - base_price) > tol:
        return False
    eps = 1e-6
    anchor = session_anchor
    if anchor <= 0:
        return True
    if anchor > base_price + eps:
        # Started above BASE — enter only when price pulls back to/at BASE (not above).
        return current_price <= base_price + eps
    if anchor < base_price - eps:
        # Started below BASE — enter only when price rises to/at BASE (not below).
        return current_price >= base_price - eps
    return abs(anchor - base_price) <= tol


def grid_level_prices(levels: list[GridLevel]) -> list[float]:
    return sorted(l.price for l in levels)


def expand_grid_traversal_path(prices: list[float], grid_prices: list[float]) -> list[float]:
    """Insert every grid level between consecutive path points (strict traversal)."""
    if not prices:
        return prices

    out: list[float] = [prices[0]]
    for target in prices[1:]:
        start = out[-1]
        if abs(target - start) < 1e-9:
            continue

        going_up = target > start
        lo, hi = min(start, target), max(start, target)
        between = [
            p
            for p in grid_prices
            if (lo + 1e-6) < p <= (hi + 1e-6) and abs(p - start) > 1e-6 and abs(p - target) > 1e-6
        ]
        between.sort(reverse=not going_up)

        for px in between:
            if abs(px - out[-1]) > 1e-9:
                out.append(px)
        if abs(target - out[-1]) > 1e-9:
            out.append(target)
    return out


def _max_upper_crossed_idx(prev_price: float, curr_price: float, levels: list[GridLevel]) -> int:
    max_idx = 0
    for lvl, direction in _crossed_levels(prev_price, curr_price, levels):
        if lvl.kind == "upper" and direction == "up":
            max_idx = max(max_idx, _upper_idx(lvl.level_id))
    return max_idx


def _max_lower_crossed_idx(prev_price: float, curr_price: float, levels: list[GridLevel]) -> int:
    max_idx = 0
    for lvl, direction in _crossed_levels(prev_price, curr_price, levels):
        if lvl.kind == "lower" and direction == "down":
            max_idx = max(max_idx, _lower_idx(lvl.level_id))
    return max_idx


def _can_exit_upper_level(level_id: str, level_states: dict[str, str]) -> bool:
    idx = _upper_idx(level_id)
    if idx <= 1:
        return True
    return all(_level_phase(level_states, f"U{j}") == "sold" for j in range(1, idx))


def _can_add_lower_level(level_id: str, level_states: dict[str, str]) -> bool:
    idx = _lower_idx(level_id)
    if idx <= 1:
        return True
    return all(_level_phase(level_states, f"D{j}") == "added" for j in range(1, idx))


def _can_add_inverted_upper(level_id: str, level_states: dict[str, str]) -> bool:
    idx = _upper_idx(level_id)
    if idx <= 1:
        return True
    return all(_level_phase(level_states, f"U{j}") == "added" for j in range(1, idx))


def _can_exit_inverted_lower(level_id: str, level_states: dict[str, str]) -> bool:
    idx = _lower_idx(level_id)
    if idx <= 1:
        return True
    return all(_level_phase(level_states, f"D{j}") == "sold" for j in range(1, idx))


def validate_grid_trade_sequence(actions: list[dict[str, Any]], *, max_upper: int = 3, max_lower: int = 3) -> list[str]:
    """Validate strict grid ladder ordering in a trade list."""
    errors: list[str] = []
    upper_sold: dict[str, bool] = {f"U{i}": False for i in range(1, max_upper + 1)}
    lower_added: dict[str, bool] = {f"D{i}": False for i in range(1, max_lower + 1)}

    for i, act in enumerate(actions):
        action = str(act.get("action") or "")
        level = str(act.get("level") or "")
        unwind_d = act.get("unwindD")

        if action in ("INITIAL_BUY", "REENTER") and level == "BASE":
            upper_sold = {f"U{j}": False for j in range(1, max_upper + 1)}
            lower_added = {f"D{j}": False for j in range(1, max_lower + 1)}

        if action == "EXIT" and level.startswith("U"):
            idx = _upper_idx(level)
            for j in range(1, idx):
                if not upper_sold.get(f"U{j}"):
                    errors.append(f"trade[{i}]: EXIT {level} missing prior EXIT U{j}")
            upper_sold[level] = True

        if action == "ADD" and level.startswith("D"):
            idx = _lower_idx(level)
            for j in range(1, idx):
                if not lower_added.get(f"D{j}"):
                    errors.append(f"trade[{i}]: ADD {level} missing prior ADD D{j}")
            lower_added[level] = True

        if action == "EXIT" and unwind_d and str(unwind_d).startswith("D"):
            deeper = str(unwind_d)
            idx = _lower_idx(deeper)
            if not lower_added.get(deeper):
                errors.append(f"trade[{i}]: unwind {deeper} at {level} without {deeper} added")
            lower_added[deeper] = False
            if idx > 1 and not any(lower_added.get(f"D{j}") for j in range(1, idx)):
                pass  # deeper level cleared

    return errors


def _touch_exit_crosses(
    current_price: float,
    levels: list[GridLevel],
    level_states: dict[str, str],
    *,
    grid_gap: float,
    invert_grid: bool,
    max_upper: int,
    max_lower: int,
) -> list[tuple[GridLevel, CrossDir]]:
    """Stale LTP parked on an exit level — fire exit without a price cross between polls."""
    out: list[tuple[GridLevel, CrossDir]] = []
    for level in levels:
        if not ltp_matches_grid_level(current_price, level.price, grid_gap):
            continue
        if invert_grid:
            if level.kind != "lower":
                continue
            if not _can_exit_inverted_lower(level.level_id, level_states):
                continue
            out.append((level, "down"))
        else:
            if level.kind != "upper":
                continue
            if not _can_exit_upper_level(level.level_id, level_states):
                continue
            out.append((level, "up"))
    return out


def _crossed_levels(prev_price: float, curr_price: float, levels: list[GridLevel]) -> list[tuple[GridLevel, CrossDir]]:
    if prev_price <= 0 or curr_price <= 0 or prev_price == curr_price:
        return []

    eps = 1e-6
    direction: CrossDir = "up" if curr_price > prev_price else "down"
    prices = sorted({l.price for l in levels}, reverse=(direction == "down"))
    crossed: list[tuple[GridLevel, CrossDir]] = []

    for price in prices:
        if direction == "up" and (prev_price - eps) < price <= (curr_price + eps):
            level = next(l for l in levels if l.price == price)
            crossed.append((level, direction))
        elif direction == "down" and (prev_price + eps) >= price > (curr_price - eps):
            level = next(l for l in levels if l.price == price)
            crossed.append((level, direction))

    if direction == "up":
        crossed.sort(key=lambda x: x[0].price)
    else:
        crossed.sort(key=lambda x: x[0].price, reverse=True)
    return crossed


def _max_sold_upper(level_states: dict[str, str], max_upper: int) -> int:
    for i in range(max_upper, 0, -1):
        if _level_phase(level_states, f"U{i}") == "sold":
            return i
    return 0


def _action_for_cross(
    level: GridLevel,
    direction: CrossDir,
    *,
    level_states: dict[str, str],
    phase: LevelPhase,
    initial_lots: int,
    lots_per_grid: int,
    base_entered: bool,
    position_lots: int,
    upper_arm_locked: bool,
    upper_reenter_held: bool,
    max_sold_upper: int,
    upper_peak_sold: int,
    levels_above: int,
    levels_below: int,
    absolute_floor: int,
    protected_floor: int,
    session_anchor_price: float = 0.0,
) -> tuple[str, int, str, LevelPhase | None, str | None]:
    """Returns action, delta, message, cross-level new phase, other level to set neutral.

    Lower-grid unwinds occur at the adjacent level above the add (D2 @ D1, D1 @ BASE).
    Upper-grid re-entries occur at the adjacent level below the exit (U3 @ U2, U1 @ BASE).
    """
    if level.kind == "base":
        if not base_entered and position_lots == 0:
            eps = 1e-6
            anchor = session_anchor_price
            if direction == "down" and (anchor <= 0 or anchor > level.price + eps):
                return "INITIAL_BUY", initial_lots, f"Buy {initial_lots} lots @ BASE", None, None
            if direction == "up" and anchor > 0 and anchor < level.price - eps:
                return "INITIAL_BUY", initial_lots, f"Buy {initial_lots} lots @ BASE", None, None
            return "SKIP", 0, "", None, None
        if direction == "up" and base_entered and _level_phase(level_states, "D1") == "added":
            qty = _max_exit_qty(
                position_lots=position_lots,
                lots_per_grid=lots_per_grid,
                floor_lots=protected_floor,
            )
            if qty <= 0:
                return "SKIP", 0, "", None, None
            return "EXIT", -qty, f"Exit {qty} lots @ BASE (unwind D1)", None, "D1"
        if direction == "down" and base_entered and _level_phase(level_states, "U1") == "sold":
            if upper_reenter_held:
                return "SKIP", 0, "", None, None
            return "REENTER", lots_per_grid, f"Buy back {lots_per_grid} lots @ BASE (reenter U1)", None, "U1"
        return "SKIP", 0, "", None, None

    if level.kind == "upper":
        idx = _upper_idx(level.level_id)
        if direction == "up" and phase == "neutral":
            if upper_arm_locked:
                return "SKIP", 0, "", None, None
            if position_lots <= 0:
                return "SKIP", 0, "", None, None
            qty = _max_exit_qty(
                position_lots=position_lots,
                lots_per_grid=lots_per_grid,
                floor_lots=absolute_floor,
            )
            if qty <= 0:
                return "SKIP", 0, "", None, None
            return "EXIT", -qty, f"Exit {qty} lots @ {level.level_id}", "sold", None
        if direction == "down":
            target = f"U{idx + 1}"
            if idx < levels_above and _level_phase(level_states, target) == "sold":
                if upper_reenter_held:
                    return "SKIP", 0, "", None, None
                return (
                    "REENTER",
                    lots_per_grid,
                    f"Buy back {lots_per_grid} lots @ {level.level_id} (reenter {target})",
                    None,
                    target,
                )
        return "SKIP", 0, "", None, None

    if level.kind == "lower":
        if not base_entered:
            return "SKIP", 0, "", None, None
        if direction == "down" and phase == "neutral":
            return "ADD", lots_per_grid, f"Add {lots_per_grid} lots @ {level.level_id}", "added", None
        if direction == "up":
            n = _lower_idx(level.level_id)
            deeper = f"D{n + 1}"
            if n < levels_below and _level_phase(level_states, deeper) == "added":
                qty = _max_exit_qty(
                    position_lots=position_lots,
                    lots_per_grid=lots_per_grid,
                    floor_lots=protected_floor,
                )
                if qty <= 0:
                    return "SKIP", 0, "", None, None
                return (
                    "EXIT",
                    -qty,
                    f"Exit {qty} lots @ {level.level_id} (unwind {deeper})",
                    None,
                    deeper,
                )
        return "SKIP", 0, "", None, None

    return "SKIP", 0, "", None, None


def _action_for_cross_inverted(
    level: GridLevel,
    direction: CrossDir,
    *,
    level_states: dict[str, str],
    phase: LevelPhase,
    initial_lots: int,
    lots_per_grid: int,
    base_entered: bool,
    position_lots: int,
    upper_arm_locked: bool,
    upper_reenter_held: bool,
    max_sold_upper: int,
    upper_peak_sold: int,
    levels_above: int,
    levels_below: int,
    absolute_floor: int,
    protected_floor: int,
    session_anchor_price: float = 0.0,
) -> tuple[str, int, str, LevelPhase | None, str | None]:
    """Opposite grid: up/down actions are swapped vs normal long grid."""
    if level.kind == "base":
        if not base_entered and position_lots == 0:
            eps = 1e-6
            anchor = session_anchor_price
            if direction == "up" and (anchor <= 0 or anchor > level.price + eps):
                return "INITIAL_BUY", initial_lots, f"Buy {initial_lots} lots @ BASE", None, None
            if direction == "down" and anchor > 0 and anchor < level.price - eps:
                return "INITIAL_BUY", initial_lots, f"Buy {initial_lots} lots @ BASE", None, None
            return "SKIP", 0, "", None, None
        if direction == "down" and base_entered and _level_phase(level_states, "U1") == "added":
            if upper_reenter_held:
                return "SKIP", 0, "", None, None
            qty = _max_exit_qty(
                position_lots=position_lots,
                lots_per_grid=lots_per_grid,
                floor_lots=protected_floor,
            )
            if qty <= 0:
                return "SKIP", 0, "", None, None
            return "EXIT", -qty, f"Exit {qty} lots @ BASE (unwind U1)", None, "U1"
        if direction == "up" and base_entered and _level_phase(level_states, "D1") == "sold":
            return "ADD", lots_per_grid, f"Add {lots_per_grid} lots @ BASE (invert D1)", None, "D1"
        return "SKIP", 0, "", None, None

    if level.kind == "upper":
        idx = _upper_idx(level.level_id)
        if direction == "up" and phase == "neutral":
            if upper_arm_locked:
                return "SKIP", 0, "", None, None
            if not base_entered:
                return "SKIP", 0, "", None, None
            return "ADD", lots_per_grid, f"Add {lots_per_grid} lots @ {level.level_id}", "added", None
        if direction == "down":
            target = f"U{idx + 1}"
            if idx < levels_above and _level_phase(level_states, target) == "added":
                if upper_reenter_held:
                    return "SKIP", 0, "", None, None
                qty = _max_exit_qty(
                    position_lots=position_lots,
                    lots_per_grid=lots_per_grid,
                    floor_lots=protected_floor,
                )
                if qty <= 0:
                    return "SKIP", 0, "", None, None
                return (
                    "EXIT",
                    -qty,
                    f"Exit {qty} lots @ {level.level_id} (unwind {target})",
                    None,
                    target,
                )
        return "SKIP", 0, "", None, None

    if level.kind == "lower":
        if not base_entered:
            return "SKIP", 0, "", None, None
        if direction == "down" and phase == "neutral":
            qty = _max_exit_qty(
                position_lots=position_lots,
                lots_per_grid=lots_per_grid,
                floor_lots=absolute_floor,
            )
            if qty <= 0:
                return "SKIP", 0, "", None, None
            return "EXIT", -qty, f"Exit {qty} lots @ {level.level_id}", "sold", None
        if direction == "up":
            n = _lower_idx(level.level_id)
            deeper = f"D{n + 1}"
            if n < levels_below and _level_phase(level_states, deeper) == "sold":
                return (
                    "ADD",
                    lots_per_grid,
                    f"Add {lots_per_grid} lots @ {level.level_id} (invert {deeper})",
                    None,
                    deeper,
                )
        return "SKIP", 0, "", None, None

    return "SKIP", 0, "", None, None


def _ui_status(
    level: GridLevel,
    phase: LevelPhase,
    *,
    base_entered: bool,
    position: int,
    arm_locked: bool,
    invert_grid: bool = False,
) -> str:
    if level.kind == "base":
        if not base_entered:
            return "Pending"
        return "Active" if position > 0 else "Pending"
    if level.kind == "upper":
        if invert_grid:
            if arm_locked and phase == "neutral":
                return "Await Higher Add"
            if phase == "added":
                n = _upper_idx(level.level_id)
                exit_at = "BASE" if n <= 1 else f"U{n - 1}"
                return f"Added · Exit @ {exit_at}"
            return "Pending"
        if arm_locked and phase == "neutral":
            return "Await Higher Exit"
        if phase == "sold":
            return "Sold · Await Buy Back"
        return "Pending"
    if level.kind == "lower":
        if invert_grid:
            if phase == "sold":
                return "Sold · Await Buy Back"
            return "Pending"
        if phase == "added":
            n = _lower_idx(level.level_id)
            exit_at = "BASE" if n <= 1 else f"D{n - 1}"
            return f"Added · Exit @ {exit_at}"
        return "Pending"
    return "Pending"


def compute_level_statuses(
    levels: list[GridLevel],
    runtime: dict[str, Any],
    current_price: float,
    *,
    invert_grid: bool = False,
) -> list[dict[str, Any]]:
    state_map: dict[str, str] = dict(runtime.get("levelStates") or {})
    arm_map: dict[str, bool] = dict(runtime.get("upperArmLocks") or {})
    position = _int(runtime.get("positionLots"))
    base_entered = bool(runtime.get("baseEntered"))

    rows: list[dict[str, Any]] = []
    for level in levels:
        phase = _level_phase(state_map, level.level_id)
        rows.append(
            {
                "level": level.level_id,
                "price": level.price,
                "action": level.action_label,
                "status": _ui_status(
                    level,
                    phase,
                    base_entered=base_entered,
                    position=position,
                    arm_locked=bool(arm_map.get(level.level_id)),
                    invert_grid=invert_grid,
                ),
            }
        )
    return rows


def compute_next_action_level(
    levels: list[GridLevel],
    runtime: dict[str, Any],
    current_price: float,
    *,
    invert_grid: bool = False,
) -> str | None:
    if current_price <= 0 or not levels:
        return None
    if not runtime.get("baseEntered"):
        return "BASE"

    state_map: dict[str, str] = dict(runtime.get("levelStates") or {})
    arm_map: dict[str, bool] = dict(runtime.get("upperArmLocks") or {})
    max_upper = max((_upper_idx(l.level_id) for l in levels if l.kind == "upper"), default=0)

    if invert_grid:
        for level in levels:
            phase = _level_phase(state_map, level.level_id)
            if level.kind == "upper" and phase == "added" and current_price < level.price:
                n = _upper_idx(level.level_id)
                return "BASE" if n <= 1 else f"U{n - 1}"
            if level.kind == "lower" and phase == "sold" and current_price > level.price:
                return level.level_id

        for level in levels:
            if level.kind == "upper" and arm_map.get(level.level_id) and current_price >= level.price:
                higher = f"U{_upper_idx(level.level_id) + 1}"
                if _level_phase(state_map, higher) == "added" or any(
                    _level_phase(state_map, f"U{n}") == "added"
                    for n in range(_upper_idx(level.level_id) + 1, max_upper + 1)
                ):
                    continue
                return higher

        return runtime.get("lastLevelId") or "BASE"

    for level in levels:
        phase = _level_phase(state_map, level.level_id)
        if level.kind == "upper" and phase == "sold" and current_price < level.price:
            return level.level_id
        if level.kind == "lower" and phase == "added":
            n = _lower_idx(level.level_id)
            return "BASE" if n <= 1 else f"D{n - 1}"

    for level in levels:
        if level.kind == "upper" and arm_map.get(level.level_id) and current_price >= level.price:
            higher = f"U{_upper_idx(level.level_id) + 1}"
            if _level_phase(state_map, higher) == "sold" or any(
                _level_phase(state_map, f"U{n}") == "sold"
                for n in range(_upper_idx(level.level_id) + 1, max_upper + 1)
            ):
                continue
            return higher

    return runtime.get("lastLevelId") or "BASE"


def fresh_grid_runtime(current_price: float = 0.0) -> dict[str, Any]:
    """Clean grid state when algo is enabled — anchor at live price, no position."""
    rt = default_runtime()
    if current_price > 0:
        rt["prevPrice"] = current_price
        rt["lastPrice"] = current_price
        rt["sessionAnchorPrice"] = current_price
    return rt


def seed_runtime_market_price(runtime: dict[str, Any], current_price: float) -> dict[str, Any]:
    """Track live market price without entering — wait until price crosses BASE."""
    rt = dict(runtime)
    if current_price <= 0:
        return rt
    if bool(rt.get("baseEntered")) or _int(rt.get("positionLots")) > 0:
        return rt
    if _num(rt.get("prevPrice")) <= 0 and _num(rt.get("lastPrice")) <= 0:
        rt["prevPrice"] = current_price
        rt["lastPrice"] = current_price
        if _num(rt.get("sessionAnchorPrice")) <= 0:
            rt["sessionAnchorPrice"] = current_price
    return rt


def bootstrap_initial_entry(
    cfg: dict[str, Any],
    runtime: dict[str, Any] | None = None,
    *,
    fill_price: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Backtest helper: assume position at reference BASE before candle processing.

    Live/paper engine must NOT call this — use seed_runtime_market_price + process_price_tick
    so INITIAL_BUY only fires when price actually crosses BASE.
    """
    parsed = parse_strategy_config(cfg)
    ref = parsed["reference_price"]
    initial = parsed["initial_lots"]
    rt = load_runtime({**cfg, "grid_runtime": runtime or {}})

    if ref <= 0 or initial <= 0:
        return rt, []
    if bool(rt.get("baseEntered")) or _int(rt.get("positionLots")) > 0:
        return rt, []

    if _num(rt.get("sessionReferencePrice")) <= 0:
        rt["sessionReferencePrice"] = ref

    levels = build_grid_levels(
        reference_price=_num(rt.get("sessionReferencePrice")) or ref,
        grid_gap=parsed["grid_gap"],
        levels_above=parsed["grid_levels_above"],
        levels_below=parsed["grid_levels_below"],
        initial_lots=initial,
        lots_per_grid=parsed["lots_per_grid"],
        invert_grid=parsed["invert_grid"],
    )
    base = next((l for l in levels if l.kind == "base"), None)
    if not base:
        return rt, []

    entry_px = round(ref, 4)
    fill = round(fill_price, 4) if fill_price and fill_price > 0 else entry_px

    rt.update(
        {
            "positionLots": initial,
            "realizedPnl": 0.0,
            "avgEntryPrice": entry_px,
            "lastPrice": entry_px,
            "prevPrice": entry_px,
            "baseEntered": True,
            "lastLevelId": "BASE",
            "levelStates": dict(rt.get("levelStates") or {}),
            "upperArmLocks": dict(rt.get("upperArmLocks") or {}),
        }
    )
    rt["nextActionLevel"] = compute_next_action_level(
        levels, rt, entry_px, invert_grid=parsed["invert_grid"]
    )

    actions = [
        {
            "action": "INITIAL_BUY",
            "level": "BASE",
            "levelPrice": round(base.price, 4),
            "fillPrice": fill,
            "price": fill,
            "lotsDelta": initial,
            "positionAfter": initial,
            "realizedPnl": 0.0,
            "message": f"Buy {initial} lots @ BASE",
            "levelPhase": "neutral",
            "crossDirection": "up",
        }
    ]
    return rt, actions


def process_price_tick(
    cfg: dict[str, Any],
    runtime: dict[str, Any],
    current_price: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns updated runtime and list of actions taken this tick.

    Traverses every grid level between previous and current price in order.
    Shared by backtest, paper, and live engines.
    """
    parsed = parse_strategy_config(cfg)
    rt = load_runtime({**cfg, "grid_runtime": runtime})
    # Freeze reference only after the grid is live; while flat, follow latest settings.
    in_trade = int(rt.get("positionLots") or 0) > 0 or bool(rt.get("baseEntered"))
    if in_trade:
        if _num(rt.get("sessionReferencePrice")) <= 0 and parsed["reference_price"] > 0:
            rt["sessionReferencePrice"] = parsed["reference_price"]
        ref_px = _num(rt.get("sessionReferencePrice")) or parsed["reference_price"]
    else:
        ref_px = parsed["reference_price"]
        if ref_px > 0:
            rt["sessionReferencePrice"] = ref_px
    levels = build_grid_levels(
        reference_price=ref_px,
        grid_gap=parsed["grid_gap"],
        levels_above=parsed["grid_levels_above"],
        levels_below=parsed["grid_levels_below"],
        initial_lots=parsed["initial_lots"],
        lots_per_grid=parsed["lots_per_grid"],
        invert_grid=parsed["invert_grid"],
    )
    if not levels or current_price <= 0:
        rt["lastPrice"] = current_price
        return rt, []

    prev_price = _num(rt.get("prevPrice")) or _num(rt.get("lastPrice"))
    if prev_price <= 0:
        prev_price = current_price

    if abs(prev_price - current_price) < 1e-9:
        step_cfg = {**cfg, "grid_runtime": rt}
        return _process_single_price_step(step_cfg, current_price, levels, parsed)

    grid_prices = grid_level_prices(levels)
    traversal = expand_grid_traversal_path([prev_price, current_price], grid_prices)

    all_actions: list[dict[str, Any]] = []
    step_cfg = {**cfg}
    for step_px in traversal[1:]:
        step_cfg["grid_runtime"] = rt
        rt, acts = _process_single_price_step(step_cfg, step_px, levels, parsed)
        all_actions.extend(acts)

    return rt, all_actions


def _process_single_price_step(
    cfg: dict[str, Any],
    current_price: float,
    levels: list[GridLevel],
    parsed: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Process one price step along a strict grid traversal path."""
    rt = load_runtime(cfg)
    prev_price = _num(rt.get("prevPrice")) or _num(rt.get("lastPrice"))
    if prev_price <= 0:
        prev_price = current_price

    actions: list[dict[str, Any]] = []
    position = _int(rt.get("positionLots"))
    realized = _num(rt.get("realizedPnl"))
    avg_entry = _num(rt.get("avgEntryPrice"))
    base_entered = bool(rt.get("baseEntered"))
    level_states: dict[str, str] = dict(rt.get("levelStates") or {})
    upper_arm_locks: dict[str, bool] = dict(rt.get("upperArmLocks") or {})
    upper_reenter_hold: dict[str, bool] = dict(rt.get("upperReenterHold") or {})
    upper_peak_sold = _int(rt.get("upperPeakSold"))
    max_upper = parsed["grid_levels_above"]
    max_lower = parsed["grid_levels_below"]
    session_anchor = _num(rt.get("sessionAnchorPrice"))
    invert_grid = bool(parsed.get("invert_grid"))
    # Exit side of the grid (upper for normal, lower for inverted) — the floor is
    # based on this side so the whole inventory can reach zero lots.
    exit_side_levels = max_lower if invert_grid else max_upper

    for i in range(2, max_upper + 1):
        lower_level = next((l for l in levels if l.level_id == f"U{i - 1}"), None)
        if lower_level and current_price <= lower_level.price + 1e-6:
            upper_reenter_hold[f"U{i}"] = False

    max_up_cross = _max_upper_crossed_idx(prev_price, current_price, levels)
    if max_up_cross >= 2:
        for j in range(1, max_up_cross):
            upper_arm_locks[f"U{j}"] = False

    base_level = next((l for l in levels if l.kind == "base"), None)
    if (
        base_level
        and not base_entered
        and position == 0
        and parsed["initial_lots"] > 0
        and _allow_base_touch_entry(session_anchor, base_level.price, current_price, parsed["grid_gap"])
    ):
        trade_price = base_level.price
        position = parsed["initial_lots"]
        avg_entry = trade_price
        base_entered = True
        actions.append(
            {
                "action": "INITIAL_BUY",
                "level": "BASE",
                "levelPrice": round(base_level.price, 4),
                "fillPrice": round(trade_price, 4),
                "price": round(trade_price, 4),
                "lotsDelta": position,
                "positionAfter": position,
                "realizedPnl": round(realized, 2),
                "message": f"Buy {position} lots @ BASE (touch)",
                "levelPhase": "neutral",
                "crossDirection": "touch",
            }
        )
        rt["lastLevelId"] = "BASE"

    crosses = _crossed_levels(prev_price, current_price, levels)
    if not crosses and position > 0 and base_entered:
        crosses = _touch_exit_crosses(
            current_price,
            levels,
            level_states,
            grid_gap=parsed["grid_gap"],
            invert_grid=invert_grid,
            max_upper=max_upper,
            max_lower=max_lower,
        )
    crossed_up_ids = {lvl.level_id for lvl, d in crosses if d == "up"}

    for level, direction in crosses:
        if level.kind == "upper" and direction == "up":
            idx = _upper_idx(level.level_id)
            deeper = f"U{idx + 1}"
            if invert_grid or not upper_arm_locks.get(level.level_id) or deeper in crossed_up_ids:
                upper_arm_locks[level.level_id] = False

        absolute_floor = _absolute_inventory_floor(
            parsed["initial_lots"], exit_side_levels, parsed["lots_per_grid"]
        )
        protected_floor = _protected_inventory_floor(
            parsed["initial_lots"],
            level_states,
            exit_side_levels,
            parsed["lots_per_grid"],
            invert_grid=invert_grid,
        )

        phase = _level_phase(level_states, level.level_id)
        max_sold = _max_sold_upper(level_states, max_upper)
        cross_fn = _action_for_cross_inverted if invert_grid else _action_for_cross
        reenter_hold_level = level.level_id
        if level.kind == "upper" and direction == "down":
            # At U4 on the way down we re-enter the position sold/added at U5,
            # so the hold belongs to U5, not the U4 crossing level.
            reenter_hold_level = f"U{_upper_idx(level.level_id) + 1}"
        action_type, delta, msg, new_phase, neutralize_level = cross_fn(
            level,
            direction,
            level_states=level_states,
            phase=phase,
            initial_lots=parsed["initial_lots"],
            lots_per_grid=parsed["lots_per_grid"],
            base_entered=base_entered,
            position_lots=position,
            upper_arm_locked=bool(upper_arm_locks.get(level.level_id)),
            upper_reenter_held=bool(upper_reenter_hold.get(reenter_hold_level)),
            max_sold_upper=max_sold,
            upper_peak_sold=upper_peak_sold,
            levels_above=max_upper,
            levels_below=max_lower,
            absolute_floor=absolute_floor,
            protected_floor=protected_floor,
            session_anchor_price=session_anchor,
        )
        if action_type == "SKIP" or delta == 0:
            continue

        if invert_grid:
            if action_type == "EXIT" and level.kind == "lower" and not _can_exit_inverted_lower(
                level.level_id, level_states
            ):
                continue
            if action_type == "ADD" and level.kind == "upper" and not _can_add_inverted_upper(
                level.level_id, level_states
            ):
                continue
        else:
            if action_type == "EXIT" and level.kind == "upper" and not _can_exit_upper_level(
                level.level_id, level_states
            ):
                continue
            if action_type == "ADD" and level.kind == "lower" and not _can_add_lower_level(
                level.level_id, level_states
            ):
                continue

        trade_price = round(level.price, 2)
        exit_qty = 0
        if delta > 0:
            if position == 0:
                avg_entry = trade_price
            else:
                avg_entry = ((avg_entry * position) + (trade_price * delta)) / (position + delta)
            position += delta
            if action_type == "INITIAL_BUY":
                base_entered = True
        else:
            exit_qty = min(abs(delta), position)
            if exit_qty <= 0:
                continue
            realized += (trade_price - avg_entry) * exit_qty
            position -= exit_qty

        if new_phase is not None:
            level_states[level.level_id] = new_phase
        if neutralize_level:
            level_states[neutralize_level] = "neutral"

        if action_type == "EXIT" and level.kind == "upper":
            idx = _upper_idx(level.level_id)
            upper_peak_sold = max(upper_peak_sold, idx)
            upper_reenter_hold[level.level_id] = True
            if idx > 1:
                upper_arm_locks[f"U{idx - 1}"] = False
            if idx < max_upper:
                upper_reenter_hold[f"U{idx - 1}"] = False

        if action_type == "REENTER" and neutralize_level and neutralize_level.startswith("U"):
            idx = _upper_idx(neutralize_level)
            upper_arm_locks[neutralize_level] = True
            upper_reenter_hold[neutralize_level] = False
            if idx < max_upper:
                upper_reenter_hold[f"U{idx + 1}"] = False
            if idx > 1:
                upper_arm_locks[f"U{idx + 1}"] = False

        actions.append(
            {
                "action": action_type,
                "level": level.level_id,
                "levelPrice": round(level.price, 4),
                "fillPrice": round(trade_price, 4),
                "price": round(trade_price, 4),
                "lotsDelta": delta if delta > 0 else -exit_qty,
                "positionAfter": position,
                "realizedPnl": round(realized, 2),
                "message": msg,
                "levelPhase": new_phase if new_phase is not None else phase,
                "crossDirection": direction,
                "unwindD": neutralize_level if neutralize_level and neutralize_level.startswith("D") else None,
                "reenterU": neutralize_level if neutralize_level and neutralize_level.startswith("U") else None,
            }
        )
        rt["lastLevelId"] = level.level_id

    if invert_grid:
        if not any(_level_phase(level_states, f"U{i}") == "added" for i in range(1, max_upper + 1)):
            upper_peak_sold = 0
    elif not any(_level_phase(level_states, f"U{i}") == "sold" for i in range(1, max_upper + 1)):
        upper_peak_sold = 0

    rt.update(
        {
            "positionLots": position,
            "realizedPnl": round(realized, 2),
            "avgEntryPrice": round(avg_entry, 4) if position > 0 else 0.0,
            "lastPrice": current_price,
            "prevPrice": current_price,
            "baseEntered": base_entered or position > 0,
            "coreLots": parsed["initial_lots"],
            "inventoryFloorLots": _absolute_inventory_floor(
                parsed["initial_lots"], exit_side_levels, parsed["lots_per_grid"]
            ),
            "protectedFloorLots": _protected_inventory_floor(
                parsed["initial_lots"],
                level_states,
                exit_side_levels,
                parsed["lots_per_grid"],
                invert_grid=invert_grid,
            ),
            "gridAddedLots": _d_added_lots(level_states, max_lower, parsed["lots_per_grid"]),
            "levelStates": level_states,
            "upperArmLocks": upper_arm_locks,
            "upperReenterHold": upper_reenter_hold,
            "upperPeakSold": upper_peak_sold,
            "nextActionLevel": compute_next_action_level(
                levels, rt, current_price, invert_grid=invert_grid
            ),
        }
    )
    return rt, actions
