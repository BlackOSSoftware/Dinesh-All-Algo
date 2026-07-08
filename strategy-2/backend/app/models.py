from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StrategySettings(Base):
    """Per-user dashboard + strategy JSON; denormalized flags for engine queries."""

    __tablename__ = "strategy_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    algo_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trading_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="PAPER")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TradePosition(Base):
    """Open or closed leg position (one OPEN row per user+leg_id)."""

    __tablename__ = "trade_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    leg_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trading_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # PUT / CALL
    range_level: Mapped[float] = mapped_column(Float, nullable=False)
    strike: Mapped[float] = mapped_column(Float, nullable=False)
    tp: Mapped[float] = mapped_column(Float, nullable=True)
    lots: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    put_sl_pts: Mapped[int] = mapped_column(Integer, nullable=True)
    call_sl_pts: Mapped[int] = mapped_column(Integer, nullable=True)
    sl_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    underlying_at_entry: Mapped[float] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exit_price: Mapped[float] = mapped_column(Float, nullable=True)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    pnl: Mapped[float] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=True)
    trading_symbol: Mapped[str] = mapped_column(String(128), nullable=True)
    symbol_token: Mapped[str] = mapped_column(String(32), nullable=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=True)
    unique_order_id: Mapped[str] = mapped_column(String(128), nullable=True)
    last_order_message: Mapped[str] = mapped_column(String(512), nullable=True)


class TradingLog(Base):
    __tablename__ = "trading_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    leg: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(128), nullable=True)
    strike: Mapped[float] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float] = mapped_column(Float, nullable=True)
    pnl: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=True)
