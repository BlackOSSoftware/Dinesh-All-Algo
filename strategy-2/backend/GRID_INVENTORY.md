# Strategy 2 MCX Grid — Inventory Accounting

## Design: exit ladder runs to zero, add ladder is capped

The strategy holds `initialLots` at BASE and trades **grid layers** around it. The **exit side** of the grid (upper levels for the buy grid, lower levels for the inverted/sell grid) automatically extends past the configured level count until the whole inventory can exit. At 0 lots the algo and persisted grid remain active; a one-grid reversal buys back `lotsPerGrid` and continues the cycle. The **add side** stays capped at the configured setting (`gridLevelsBelow` for buy grid / `gridLevelsAbove` for inverted).

| Concept | Definition |
|---------|------------|
| **Core lots** | `initialLots` (e.g. 10) bought at BASE / reference price |
| **Upper grid (U1…Un)** | Sells of `lotsPerGrid` (e.g. 2) on up-cross; extended to `ceil(initialLots / lotsPerGrid)` levels so all lots can exit |
| **Lower grid (D1–D3)** | Adds of `lotsPerGrid` on down-cross, capped at `gridLevelsBelow`; marked `added` until unwound at the level above |
| **Physical position** | Lots currently held (shown as `positionLots` in backtest / runtime) |
| **Inventory floor (absolute)** | `initialLots − (exit_side_levels × lotsPerGrid)` — normally **0** since the exit side extends |
| **Protected floor** | `initialLots − (sold_exit_count × lotsPerGrid)` — BASE unwind cannot go below |

### Example (ref=280, core=10, gap=2, 2 lots/grid, 3 configured upper levels)

| State | Position | Notes |
|-------|----------|-------|
| After INITIAL BUY | 10 | Core fully held |
| After U1@282 exit | 8 | 2 lots sold, awaiting buy-back on down-cross |
| After U1+U2+U3 (price 287) | 4 | Configured levels done — grid keeps going |
| Gap open 288 (U4) | 2 | Exit ladder extended automatically |
| 290 (U5) | 0 | All lots sold; grid remains active |
| Reverse to 288 (U4) | 2 | Buy back 2 lots and continue |
| After D1 add (from 10) | 12 | +2 grid inventory (adds capped at D3) |
| BASE unwind (D1) | 10 | Removes D add only |

Position **may be below core**, including 0, when upper legs are sold; those lots are tracked as `sold` on U levels and re-enter one grid level at a time on the way down. Reaching 0 does not end the grid session.

## Exit priority

1. **U exit (up-cross):** sell `min(lotsPerGrid, position − floor)` — never below floor.
2. **BASE unwind (up-cross, D added):** same cap — only removes D-added lots, never core below floor.
3. **D add (down-cross):** always +`lotsPerGrid` when level is `neutral`.

## Runtime fields (persisted in `grid_runtime`)

- `coreLots` — copy of configured initial lots
- `inventoryFloorLots` — absolute minimum (initial − exit_side_levels × lots_per_grid, normally 0)
- `protectedFloorLots` — current floor for BASE unwind (initial − sold_exit_count × lots_per_grid)
- `gridAddedLots` — count of active D adds × lots per grid
- `levelStates` — per-level `neutral` / `sold` / `added`

## Backtest vs live

Same `grid_logic.py` drives paper, live engine, and backtest. Inventory rules are identical.
