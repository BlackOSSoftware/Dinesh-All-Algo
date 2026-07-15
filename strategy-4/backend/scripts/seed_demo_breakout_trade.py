#!/usr/bin/env python3
"""
Seed Strategy 4 dashboard with one sample Crude Oil completed trade + timeline logs.

Usage (from strategy-4/backend):
  .\\.venv\\Scripts\\python.exe scripts\\seed_demo_breakout_trade.py

Or double-click: strategy-4\\Seed Demo Trade.cmd
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _ist(y: int, m: int, d: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


def main() -> int:
    from app.database import SessionLocal
    from app.models import TradePosition, TradingLog, User
    from app.services import trading_repository as tr
    from app.services.breakout_logic import fresh_breakout_runtime, save_runtime

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").one_or_none()
        if user is None:
            user = db.query(User).order_by(User.id.asc()).first()
        if user is None:
            print("No user found. Start Strategy 4 backend once so admin user is created.", file=sys.stderr)
            return 1

        uid = int(user.id)
        symbol = "CRUDEOIL20JUL26FUT"
        lots = 4
        lotsize = 10
        qty = lots * lotsize
        entry = 7654.0
        tp = 7634.0
        sl = 7664.0
        exit_px = 7634.0
        pnl = 80.0  # (7654 - 7634) * 4 lots (points × lots)

        t_ref = _ist(2026, 7, 15, 19, 59, 0)
        t_entry = _ist(2026, 7, 15, 20, 0, 0)
        t_exit = _ist(2026, 7, 15, 20, 2, 0)

        # Settings: Crude Oil breakout matching this sample day
        cfg = tr.load_config_dict(db, uid)
        cfg.update(
            {
                "market": "CRUDE_OIL",
                "startTime": "19:59",
                "endTime": "23:30",
                "lotSize": lots,
                "breakoutDistance": 5,
                "takeProfit": 20,
                "stopLoss": 10,
            }
        )
        rt = fresh_breakout_runtime(session_date="2026-07-15", last_price=exit_px)
        rt.update(
            {
                "phase": "DONE",
                "market": "CRUDE_OIL",
                "startTime": "19:59",
                "breakoutDistance": 5.0,
                "referencePrice": 7659.0,
                "buyTrigger": 7664.0,
                "sellTrigger": 7654.0,
                "refCandleTime": t_ref.isoformat(),
                "refSymbol": symbol,
                "side": "SELL",
                "entryPrice": entry,
                "tpPrice": tp,
                "slPrice": sl,
                "isReverse": False,
                "tradeCount": 1,
                "positionLots": 0,
                "realizedPnl": pnl,
                "lastPrice": exit_px,
                "message": "Strategy complete for the day · Initial SELL TP @7634.00 · P&L +80.00",
            }
        )
        cfg = save_runtime(cfg, rt)
        tr.save_strategy_settings(db, uid, config=cfg, trading_mode="PAPER")

        # Clear previous demo rows (optional cleanup of today's seeded demo messages)
        for pos in list(tr.list_completed_positions(db, uid, limit=50)):
            if pos.trading_symbol == symbol and float(pos.entry_price or 0) == entry:
                db.delete(pos)
        for log in list(tr.list_trading_logs(db, uid, limit=200)):
            if log.symbol == symbol and log.action in {
                "REFERENCE_SET",
                "INITIAL_SELL",
                "EXIT_TP",
                "STRATEGY_FINISHED",
                "SELL_TRIGGER",
            }:
                db.delete(log)
        db.commit()

        pos = TradePosition(
            user_id=uid,
            leg_id="MAIN",
            trading_mode="PAPER",
            side="SELL",
            range_level=entry,
            strike=entry,
            tp=tp,
            lots=lots,
            quantity=qty,
            put_sl_pts=int(sl),  # stash SL price for display (points field reused as absolute SL level)
            entry_price=entry,
            entry_time=t_entry.astimezone(timezone.utc),
            exit_price=exit_px,
            exit_time=t_exit.astimezone(timezone.utc),
            pnl=pnl,
            exit_reason="EXIT_TP",
            status="CLOSED",
            exchange="MCX",
            trading_symbol=symbol,
            last_order_message="Demo seed · Initial SELL TP hit",
        )
        db.add(pos)
        db.commit()

        logs = [
            (
                t_ref,
                "REF",
                "REFERENCE_SET",
                None,
                7659.0,
                None,
                None,
                "19:59 Reference Candle · O 7657.00 · H 7665.00 · L 7657.00 · C 7659.00",
            ),
            (
                t_entry,
                "SELL",
                "SELL_TRIGGER",
                qty,
                None,
                None,
                None,
                "20:00 Sell Trigger @7654.00 · Low 7650.00 · Buy Trigger @7664.00 not touched",
            ),
            (
                t_entry,
                "SELL",
                "INITIAL_SELL",
                qty,
                entry,
                None,
                None,
                f"20:00 Initial SELL · Entry @{entry:.2f} · TP {tp:.2f} · SL {sl:.2f} · {lots} lots",
            ),
            (
                t_exit,
                "SELL",
                "EXIT_TP",
                qty,
                None,
                exit_px,
                pnl,
                f"20:02 TP Hit · Exit @{exit_px:.2f} · P&L +{pnl:.2f}",
            ),
            (
                t_exit,
                "-",
                "STRATEGY_FINISHED",
                None,
                None,
                None,
                pnl,
                "20:02 Strategy Finished · Day P&L +80.00",
            ),
        ]
        for created, leg, action, quantity, entry_px, exit_p, log_pnl, message in logs:
            row = TradingLog(
                user_id=uid,
                created_at=created.astimezone(timezone.utc),
                mode="PAPER",
                leg=leg,
                action=action,
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_px,
                exit_price=exit_p,
                pnl=log_pnl,
                status="OK",
                message=message,
            )
            db.add(row)
        db.commit()

        print("--- OK: Strategy 4 demo trade seeded ---")
        print(f"user_id={uid} ({user.username})")
        print(f"Completed: Initial SELL {entry} -> {exit_px} EXIT_TP pnl=+{pnl}")
        print("Logs: REFERENCE_SET · SELL_TRIGGER · INITIAL_SELL · EXIT_TP · STRATEGY_FINISHED")
        print("Open Strategy 4 dashboard and refresh Completed Trades + Logs.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
