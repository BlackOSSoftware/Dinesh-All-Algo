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
    entry_price: float | None = None
    exit_price: float | None = None
    pnl: float | None = None
    trading_mode: str
    exit_reason: str | None = None


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


class MarketQuoteOut(BaseModel):
    key: str
    label: str
    price: float
    market_open: bool
    source: str
    tradingsymbol: str = ""
    price_type: str = "LTP"
    error: str | None = None


class GridLevelOut(BaseModel):
    level: str
    price: float
    action: str
    status: str


class DashboardOut(BaseModel):
    config: dict[str, Any]
    algo_running: bool
    trading_mode: str
    quotes: list[MarketQuoteOut]
    grid_levels: list[GridLevelOut]
    reference_price: float
    position_lots: int
    realized_pnl: float
    unrealized_pnl: float
    current_market_price: float
    next_action_level: str | None = None
    active_trades: list[ActivePositionOut]
    completed_trades: list[CompletedPositionOut]
    logs: list[TradingLogOut]
    last_live_error: str | None = None
    last_live_error_at: str | None = None


class GridBacktestRunIn(BaseModel):
    fromDate: str
    toDate: str
    startTime: str = "09:15"
    endTime: str = "23:30"
    market: str = "CRUDE_OIL"
    referencePrice: float = 0
    initialLots: int = 0
    gridGap: float = 0
    gridLevelsAbove: int = 0
    gridLevelsBelow: int = 0
    lotsPerGrid: int = 0
    invertGrid: bool = False
    buySideMonth: int = 7
    sellSideMonth: int = 8
    buySideExpiry: str = ""
    sellSideExpiry: str = ""


class McxExpiryOut(BaseModel):
    expiry: str
    expiryLabel: str
    tradingsymbol: str
    token: str
    lotsize: str
    label: str
    exchange: str = "MCX"
    key: str


class GridBacktestTradeOut(BaseModel):
    id: int
    date: str
    time: str
    action: str
    level: str
    lotsDelta: int
    side: str
    lots: int
    levelPrice: float = 0
    fillPrice: float = 0
    price: float = 0
    entryPrice: float | None = None
    exitPrice: float | None = None
    gridEntryPrice: float | None = None
    gridExitPrice: float | None = None
    positionAfter: int
    realizedPnl: float
    message: str
    symbol: str


class GridBacktestOut(BaseModel):
    ok: bool
    message: str = ""
    instrument: str = ""
    market: str = ""
    fromDate: str = ""
    toDate: str = ""
    daysRun: int = 0
    skippedDays: int = 0
    skippedDates: list[str] = Field(default_factory=list)
    summary: dict[str, Any]
    gridLevels: list[dict[str, Any]]
    daySummaries: list[dict[str, Any]]
    trades: list[GridBacktestTradeOut]
    candles: list[dict[str, Any]]
    chartTrades: list[GridBacktestTradeOut]
    chartSubtitle: str = ""
    referencePrice: float = 0
