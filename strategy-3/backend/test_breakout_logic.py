"""Unit tests for Strategy 3 breakout logic."""

from app.services.breakout_backtest import (
    next_loss_recovery_multiplier,
    should_update_recovery_multiplier,
)
from app.services.breakout_logic import (
    CandleBar,
    calc_entry_price,
    calc_stop_price,
    calc_target_price,
    entry_percentage_for_premium,
    evaluate_option_setup,
    find_window_reference_bar,
    nearest_itm_ce_strike,
    nearest_itm_pe_strike,
    reference_candle_end_hhmm,
    resample_bars,
    simulate_option_trade,
)


def test_itm_strikes_example():
    ref = 77136.0
    assert nearest_itm_ce_strike(ref) == 77100.0
    assert nearest_itm_pe_strike(ref) == 77200.0


def test_ce_entry_example():
    setup = evaluate_option_setup(
        side="CE",
        strike=77100,
        premium_close=95.60,
        target_pct=25,
        stop_pct=30,
    )
    assert setup.tradable is True
    assert setup.entry_pct == 0.30
    assert setup.entry_price == calc_entry_price(95.60, 0.30)
    assert abs(setup.entry_price - 124.28) < 0.01
    assert abs(setup.target_price - calc_target_price(124.28, 25)) < 0.02
    assert abs(setup.stop_price - calc_stop_price(124.28, 30)) < 0.02


def test_pe_no_trade_above_125():
    setup = evaluate_option_setup(
        side="PE",
        strike=77200,
        premium_close=127.65,
        target_pct=25,
        stop_pct=30,
    )
    assert setup.tradable is False
    assert "Premium >" in (setup.skip_reason or "")


def test_premium_tiers_count():
    from app.services.breakout_logic import default_premium_tiers

    assert len(default_premium_tiers()) == 6


def test_entry_pct_boundaries():
    assert entry_percentage_for_premium(25) == 0.65
    assert entry_percentage_for_premium(25.01) == 0.55
    assert entry_percentage_for_premium(126) is None


def test_custom_entry_pct_from_config():
    cfg = {"premiumTiers": [{"maxPremium": 25, "entryPercent": 70}, {"maxPremium": 125, "entryPercent": 20}]}
    assert entry_percentage_for_premium(20, cfg) == 0.70


def test_reference_candle_end():
    assert reference_candle_end_hhmm("14:35", 10) == "14:45"
    assert reference_candle_end_hhmm("14:45", 10) == "14:55"


def test_find_reference_bar_exact_start():
    bars = [
        CandleBar(time="2026-06-04T14:35:00+05:30", open=1, high=2, low=1, close=100),
        CandleBar(time="2026-06-04T14:45:00+05:30", open=1, high=2, low=1, close=200),
    ]
    ref = find_window_reference_bar(bars, "14:35")
    assert ref is not None
    assert ref.close == 100


def test_resample_1m_to_10m():
    bars = [
        CandleBar(time="2026-06-04T14:35:00+05:30", open=90, high=110, low=88, close=109),
        CandleBar(time="2026-06-04T14:36:00+05:30", open=109, high=118, low=100, close=104),
        CandleBar(time="2026-06-04T14:44:00+05:30", open=100, high=105, low=95, close=102),
        CandleBar(time="2026-06-04T14:45:00+05:30", open=102, high=130, low=98, close=125),
    ]
    out = resample_bars(bars, 10, session_open_hhmm="09:15")
    assert len(out) == 2
    assert out[0].high == 118
    assert out[0].close == 102
    assert out[1].high == 130


def test_simulate_trigger_and_target_same_bar():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    assert setup.entry_price is not None
    ref = CandleBar(time="2026-06-11T14:35:00+05:30", open=90, high=95, low=88, close=95.6)
    trigger = CandleBar(
        time="2026-06-11T14:45:00+05:30",
        open=120,
        high=setup.target_price + 1,
        low=setup.entry_price - 1,
        close=130,
    )
    sim = simulate_option_trade([ref, trigger], setup, start_idx=1)
    assert sim["status"] == "TARGET_HIT"
    assert sim["fill_time"] == trigger.time
    assert sim["exit_time"] == trigger.time
    assert sim["entry_price"] == setup.entry_price


def test_simulate_no_entry_before_monitor_candle():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    ref = CandleBar(time="2026-06-11T14:35:00+05:30", open=90, high=200, low=88, close=95.6)
    sim = simulate_option_trade([ref], setup, start_idx=1)
    assert sim["status"] == "PENDING_ENTRY"


def test_simulate_rule9_bearish_sl_same_bar():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    assert setup.entry_price is not None
    ref = CandleBar(time="2026-06-11T14:35:00+05:30", open=90, high=95, low=88, close=95.6)
    trigger = CandleBar(
        time="2026-06-11T14:45:00+05:30",
        open=120,
        high=130,
        low=setup.stop_price - 1,
        close=110,
    )
    sim = simulate_option_trade([ref, trigger], setup, start_idx=1)
    assert sim["status"] == "STOPLOSS_HIT"
    assert sim["exit_price"] == setup.stop_price


def test_simulate_ambiguous_same_bar_tp_and_sl():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    assert setup.entry_price is not None
    # Wide 10m-style bar: both TP and SL touched after entry
    bar = CandleBar(
        time="2026-06-04T14:45:00+05:30",
        open=120,
        high=162.8,
        low=23.85,
        close=150,
    )
    sim = simulate_option_trade([bar], setup, start_idx=0, ambiguous_policy="mark")
    assert sim["status"] == "AMBIGUOUS"
    assert sim["same_bar_tp_sl_conflict"] is True
    assert sim["best_case_pnl"] == round(setup.target_price - setup.entry_price, 2)
    assert sim["worst_case_pnl"] == round(setup.stop_price - setup.entry_price, 2)


def test_simulate_1m_clear_target_after_entry():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    entry_bar = CandleBar(time="2026-06-04T14:45:00+05:30", open=110, high=116, low=109, close=115)
    tp_bar = CandleBar(time="2026-06-04T14:46:00+05:30", open=116, high=setup.target_price + 1, low=115, close=150)
    sim = simulate_option_trade([entry_bar, tp_bar], setup, start_idx=0, monitor_resolution_minutes=1)
    assert sim["status"] == "TARGET_HIT"
    assert sim["same_bar_tp_sl_conflict"] is False


def test_simulate_pending_tracks_highest_during_monitoring():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    ref = CandleBar(time="2026-06-11T14:35:00+05:30", open=90, high=95, low=88, close=95.6)
    monitor = CandleBar(time="2026-06-11T14:45:00+05:30", open=80, high=90, low=70, close=85)
    sim = simulate_option_trade([ref, monitor], setup, start_idx=1)
    assert sim["status"] == "PENDING_ENTRY"
    assert sim["highest_during_monitoring"] == 90
    assert setup.entry_price is not None
    assert sim["highest_during_monitoring"] < setup.entry_price


def test_simulate_market_close():
    setup = evaluate_option_setup(
        side="CE", strike=77100, premium_close=95.60, target_pct=25, stop_pct=30,
    )
    ref = CandleBar(time="2026-06-11T14:35:00+05:30", open=90, high=95, low=88, close=95.6)
    entry_bar = CandleBar(
        time="2026-06-11T14:45:00+05:30",
        open=setup.entry_price,
        high=setup.entry_price + 5,
        low=setup.entry_price - 1,
        close=setup.entry_price + 2,
    )
    last = CandleBar(time="2026-06-11T15:25:00+05:30", open=130, high=135, low=125, close=140)
    sim = simulate_option_trade([ref, entry_bar, last], setup, start_idx=1)
    assert sim["status"] == "MARKET_CLOSE"
    assert sim["exit_price"] == 140


def test_loss_recovery_doubles_after_each_loss():
    assert next_loss_recovery_multiplier(current_multiplier=1, pnl=-100) == 2
    assert next_loss_recovery_multiplier(current_multiplier=2, pnl=-50) == 4


def test_loss_recovery_resets_after_non_loss():
    assert next_loss_recovery_multiplier(current_multiplier=4, pnl=0) == 1
    assert next_loss_recovery_multiplier(current_multiplier=4, pnl=120) == 1


def test_recovery_multiplier_ignores_non_executed_statuses():
    assert should_update_recovery_multiplier("STOPLOSS_HIT") is True
    assert should_update_recovery_multiplier("TARGET_HIT") is True
    assert should_update_recovery_multiplier("DATA_ERROR") is False
    assert should_update_recovery_multiplier("PENDING_ENTRY") is False
