"""Per-entry lot ladder."""

from app.services.sensex_trend_core import TrendParams, lots_for_entry, normalize_entry_lots


def test_normalize_entry_lots_from_array():
    p = TrendParams(max_entries=4, initial_lots=2, add_lots=1, entry_lots=[3, 2, 1, 4])
    assert p.entry_lots == [3, 2, 1, 4]
    assert lots_for_entry(p, 0) == 3
    assert lots_for_entry(p, 3) == 4


def test_normalize_entry_lots_fallback():
    p = TrendParams(max_entries=4, initial_lots=2, add_lots=1)
    assert p.entry_lots == [2, 1, 1, 1]


def test_from_config_entry_lots():
    p = TrendParams.from_config({"maxEntries": 4, "entryLots": [5, 2, 2, 1]})
    assert p.entry_lots == [5, 2, 2, 1]
    assert lots_for_entry(p, 2) == 2
