"""Compute aggregate backtest statistics from daily reports and round trips."""

from __future__ import annotations

from typing import Any


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compute_backtest_statistics(
    *,
    daily_reports: list[dict[str, Any]],
    all_round_trips: list[dict[str, Any]],
    skipped_days: int,
    total_calendar_days: int,
) -> dict[str, Any]:
    trading_days = len(daily_reports)
    buy_trades = sum(1 for d in daily_reports if d.get("initialDirection") == "BUY")
    sell_trades = sum(1 for d in daily_reports if d.get("initialDirection") == "SELL")
    reverse_trades = sum(1 for t in all_round_trips if t.get("entryType") == "Reverse")

    initial_trips = [t for t in all_round_trips if t.get("entryType") == "Initial"]
    reverse_trip_list = [t for t in all_round_trips if t.get("entryType") == "Reverse"]

    def _wins(trips: list[dict[str, Any]]) -> int:
        return sum(1 for t in trips if _num(t.get("tradePnl")) > 0)

    def _losses(trips: list[dict[str, Any]]) -> int:
        return sum(1 for t in trips if _num(t.get("tradePnl")) < 0)

    def _breakeven(trips: list[dict[str, Any]]) -> int:
        return sum(1 for t in trips if _num(t.get("tradePnl")) == 0)

    win_initial = _wins(initial_trips)
    loss_initial = _losses(initial_trips)
    win_reverse = _wins(reverse_trip_list)
    loss_reverse = _losses(reverse_trip_list)
    breakeven_initial = _breakeven(initial_trips)
    breakeven_reverse = _breakeven(reverse_trip_list)

    trade_pnls = [_num(t.get("tradePnl")) for t in all_round_trips]
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    total_pnl = sum(trade_pnls)
    win_rate = (len(wins) / len(trade_pnls) * 100.0) if trade_pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

    # Max drawdown on cumulative daily PnL
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for d in daily_reports:
        cumulative += _num(d.get("pnl"))
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    durations = [int(t["durationMinutes"]) for t in all_round_trips if t.get("durationMinutes") is not None]
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    expectancy = (total_pnl / len(trade_pnls)) if trade_pnls else 0.0

    win_days = sum(1 for d in daily_reports if _num(d.get("pnl")) > 0)
    loss_days = sum(1 for d in daily_reports if _num(d.get("pnl")) < 0)

    return {
        "totalTradingDays": trading_days,
        "totalCalendarDays": total_calendar_days,
        "skippedDays": skipped_days,
        "totalTrades": len(all_round_trips),
        "totalPnl": round(total_pnl, 2),
        "buyTrades": buy_trades,
        "sellTrades": sell_trades,
        "reverseTrades": reverse_trades,
        "winningInitialTrades": win_initial,
        "losingInitialTrades": loss_initial,
        "winningReverseTrades": win_reverse,
        "losingReverseTrades": loss_reverse,
        "breakevenInitialTrades": breakeven_initial,
        "breakevenReverseTrades": breakeven_reverse,
        "winRate": round(win_rate, 2),
        "averageWin": round(avg_win, 2),
        "averageLoss": round(avg_loss, 2),
        "profitFactor": round(profit_factor, 2),
        "maxDrawdown": round(max_dd, 2),
        "expectancy": round(expectancy, 2),
        "averageTradeDurationMinutes": round(avg_duration, 1),
        "winDays": win_days,
        "lossDays": loss_days,
        "netDays": win_days - loss_days,
    }
