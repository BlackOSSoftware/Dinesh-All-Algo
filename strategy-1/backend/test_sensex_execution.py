"""Execution layer tests — tick cross bridge and orphan state repair."""

from unittest.mock import MagicMock, patch

from app.services.sensex_execution import enrich_bar_for_tick_cross, repair_orphan_execution_state


def test_enrich_bar_spans_tick_jump():
    bar = enrich_bar_for_tick_cross(
        {"open": 77500.0, "high": 77500.0, "low": 77500.0, "close": 77500.0},
        ltp=77497.5,
        prev_ltp=77500.0,
    )
    assert bar["high"] == 77500.0
    assert bar["low"] == 77497.5
    assert bar["prev_close"] == 77500.0


def test_repair_clears_initial_entry_consumed_without_position():
    runtime = {"initial_entry_consumed": True, "cycle_id": 3, "core_lots": 2}
    db = MagicMock()
    with patch("app.services.sensex_execution.tr.get_open_position_by_leg", return_value=None), patch(
        "app.services.sensex_execution.tr.merge_strategy_runtime"
    ):
        out = repair_orphan_execution_state(db, 1, runtime)
    assert out["initial_entry_consumed"] is False
    assert "cycle_id" not in out
