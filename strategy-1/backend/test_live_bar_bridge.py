"""Real-time bridge tests: live LTP snapshots -> evolving minute OHLC."""

from datetime import datetime

from app.services import trading_engine as eng


def test_live_bar_keeps_prev_minute_close_and_updates_hilo():
    orig_now = eng._now_ist
    try:
        eng._prev_index_ltp = 77678.03
        eng._live_bar_state = None

        eng._now_ist = lambda: datetime(2026, 7, 20, 12, 52, 1)
        bar = eng._update_live_bar(77450.0)
        assert bar["prev_close"] == 77678.03
        assert bar["open"] == 77450.0
        assert bar["high"] == 77450.0
        assert bar["low"] == 77450.0

        eng._now_ist = lambda: datetime(2026, 7, 20, 12, 52, 20)
        bar = eng._update_live_bar(77528.29)
        assert bar["minute"] == "2026-07-20 12:52"
        assert bar["open"] == 77450.0
        assert bar["high"] == 77528.29
        assert bar["low"] == 77450.0
        assert bar["close"] == 77528.29

        eng._now_ist = lambda: datetime(2026, 7, 20, 12, 52, 45)
        bar = eng._update_live_bar(77490.0)
        assert bar["high"] == 77528.29
        assert bar["low"] == 77450.0
        assert bar["close"] == 77490.0

        eng._now_ist = lambda: datetime(2026, 7, 20, 12, 53, 0)
        bar = eng._update_live_bar(77510.0)
        assert bar["minute"] == "2026-07-20 12:53"
        assert bar["prev_close"] == 77490.0
        assert bar["open"] == 77510.0
        assert bar["high"] == 77510.0
        assert bar["low"] == 77510.0
    finally:
        eng._now_ist = orig_now
        eng._prev_index_ltp = None
        eng._live_bar_state = None
