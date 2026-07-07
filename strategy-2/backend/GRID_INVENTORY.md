# Strategy 2 MCX Grid — Inventory Accounting

## Design: Option A (core + grid layers)

The strategy maintains a **permanent core inventory** at BASE and trades **grid layers** around it. Full liquidation to zero is **not** intended under default settings.

| Concept | Definition |
|---------|------------|
| **Core lots** | `initialLots` (e.g. 10) bought at BASE / reference price |
| **Upper grid (U1–U3)** | Temporary sells of `lotsPerGrid` (e.g. 2) on up-cross; marked `sold` until re-enter on down-cross |
| **Lower grid (D1–D3)** | Temporary adds of `lotsPerGrid` on down-cross; marked `added` until unwound at BASE on up-cross |
| **Physical position** | Lots currently held (shown as `positionLots` in backtest / runtime) |
| **Inventory floor (absolute)** | `initialLots − (gridLevelsAbove × lotsPerGrid)` — hard minimum (e.g. 4) |
| **Protected floor** | `initialLots − (sold_upper_count × lotsPerGrid)` — BASE unwind cannot go below |

### Example (ref=300, core=10, gap=2, 2 lots/grid, 3 upper levels)

| State | Position | Absolute floor | Protected floor | Notes |
|-------|----------|----------------|-----------------|-------|
| After INITIAL BUY | 10 | 4 | 10 | Core fully held |
| After U1 exit | 8 | 4 | 8 | 2 lots sold at U1, awaiting buy-back |
| After U1+U2 exit | 6 | 4 | 6 | |
| After U1+U2+U3 exit | 4 | 4 | 4 | **Minimum position** (10 − 3×2) |
| After D1 add (from 10) | 12 | 4 | 10 | +2 grid inventory |
| BASE unwind (D1) | 10 | 4 | 10 | Removes D add only; cannot touch sold-U allocation |

Position **may be below core** (e.g. 8) when upper legs are sold — that is **not** full liquidation; those lots are tracked as `sold` on U levels and should re-enter on the way down.

Position **must not** go below the absolute inventory floor (4 with defaults). If backtest showed 0, that was a bug (U exits used the wrong floor and blocked sells, or exits were uncapped); fixed by separating **absolute** vs **protected** floors.

## Exit priority

1. **U exit (up-cross):** sell `min(lotsPerGrid, position − floor)` — never below floor.
2. **BASE unwind (up-cross, D added):** same cap — only removes D-added lots, never core below floor.
3. **D add (down-cross):** always +`lotsPerGrid` when level is `neutral`.

## Runtime fields (persisted in `grid_runtime`)

- `coreLots` — copy of configured initial lots
- `inventoryFloorLots` — absolute minimum (initial − max_upper × lots_per_grid)
- `protectedFloorLots` — current floor for BASE unwind (initial − sold_upper_count × lots_per_grid)
- `gridAddedLots` — count of active D adds × lots per grid
- `levelStates` — per-level `neutral` / `sold` / `added`

## Backtest vs live

Same `grid_logic.py` drives paper, live engine, and backtest. Inventory rules are identical.
