"""Strike selection rules for SENSEX adaptive trend."""

from app.services.sensex_trend_core import (
    EntryKind,
    nearest_strike,
    resolve_signal_strike,
    strike_from_trigger,
)


# --- CALL: ceil(index + offset) ---

def test_initial_call_strike_ceil():
    assert strike_from_trigger(76778, "CALL", 200) == 77000
    assert strike_from_trigger(77345.26, "CALL", 200) == 77600
    assert strike_from_trigger(78166, "CALL", 200) == 78400
    assert strike_from_trigger(77360.55, "CALL", 200) == 77600


def test_reentry_call_strike_ceil():
    # 76810 + 200 = 77010 → 77100 (not nearest 77000)
    assert strike_from_trigger(76810, "CALL", 200) == 77100


# --- PUT: floor(index - offset) ---

def test_initial_put_strike_floor():
    assert strike_from_trigger(76741.33, "PUT", 200) == 76500
    assert strike_from_trigger(77785, "PUT", 200) == 77500


def test_initial_put_at_trigger_floor():
    # Put trigger 76396 − 200 = 76196 → floor 76100 PE (nearest lower 100)
    assert strike_from_trigger(76396, "PUT", 200) == 76100
    assert strike_from_trigger(76741.33, "PUT", 200) == 76500


def test_reentry_put_strike_floor():
    assert strike_from_trigger(76675.95, "PUT", 200) == 76400
    assert strike_from_trigger(76626.99, "PUT", 200) == 76400


# --- AVG: nearest strike, no offset ---

def test_averaging_nearest_strike_call():
    assert nearest_strike(76733) == 76700
    assert nearest_strike(76688) == 76700
    assert nearest_strike(76643) == 76600
    assert nearest_strike(76598) == 76600
    assert nearest_strike(76765) == 76800
    assert nearest_strike(76720) == 76700
    assert nearest_strike(76675) == 76700
    assert nearest_strike(77300.26) == 77300


def test_resolve_signal_strike_modes():
    assert resolve_signal_strike(
        side="CALL", index_price=76778, entry_kind=EntryKind.INITIAL, strike_offset=200
    ) == 77000
    assert resolve_signal_strike(
        side="CALL", index_price=77345.26, entry_kind=EntryKind.REENTRY, strike_offset=200
    ) == 77600
    assert resolve_signal_strike(
        side="PUT", index_price=76675.95, entry_kind=EntryKind.REENTRY, strike_offset=200
    ) == 76400
    assert resolve_signal_strike(
        side="CALL", index_price=76643, entry_kind=EntryKind.AVERAGE, strike_offset=200
    ) == 76600


def test_reentry_avg_nearest_strike():
    assert nearest_strike(76820) == 76800
    assert nearest_strike(76775) == 76800
    assert nearest_strike(76720) == 76700
