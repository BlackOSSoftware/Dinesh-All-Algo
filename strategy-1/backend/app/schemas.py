from typing import Any, Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordChangeBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=4, max_length=128)


class TradingSettingsPut(BaseModel):
    """Full dashboard JSON plus engine flags (partial update supported)."""

    config: dict[str, Any] | None = None
    algo_running: bool | None = None
    trading_mode: Literal["PAPER", "LIVE"] | None = None


class TradingSettingsOut(BaseModel):
    config: dict[str, Any]
    algo_running: bool
    trading_mode: str


class TradingLogOut(BaseModel):
    id: int
    created_at: str
    mode: str
    leg: str
    action: str
    symbol: str | None = None
    strike: float | None = None
    quantity: int | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    status: str | None = None
    order_id: str | None = None
    message: str | None = None


class ActivePositionOut(BaseModel):
    id: int
    leg_id: str
    side: str
    strike: float
    lots: int
    quantity: int
    entry_price: float
    current_price: float
    pnl: float
    status: str
    trading_mode: str
    entry_time: str | None = None
    symbol: str | None = None
    index_entry: float | None = None
    tp1_level: float | None = None
    tp2_trail_level: float | None = None
    sl_level: float | None = None
    tp1_hit: bool = False
    order_id: str | None = None
    last_order_message: str | None = None


class CompletedPositionOut(BaseModel):
    id: int
    entry_time: str | None = None
    exit_time: str | None = None
    leg_id: str
    side: str | None = None
    range_level: float | None = None
    strike: float | None = None
    tp: float | None = None
    symbol: str | None = None
    index_entry: float | None = None
    index_exit: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    trading_mode: str
    exit_reason: str | None = None
    lots: int | None = None


class OrderCancelBody(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    variety: str = "NORMAL"


class OrderModifyBody(BaseModel):
    order_id: str
    variety: str = "NORMAL"
    tradingsymbol: str
    symboltoken: str
    transaction_type: str = "BUY"
    exchange: str = "BFO"
    order_type: str = "LIMIT"
    product_type: str = "CARRYFORWARD"
    duration: str = "DAY"
    quantity: int = 1
    price: str = "0"
