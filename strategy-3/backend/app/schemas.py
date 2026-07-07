from typing import Any

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


class TradingSettingsOut(BaseModel):
    config: dict[str, Any]
    algo_running: bool
    trading_mode: str
    expiry_info: dict[str, Any] = {}


class TradingSettingsPut(BaseModel):
    config: dict[str, Any] | None = None
    algo_running: bool | None = None
    trading_mode: str | None = None


class MarketQuoteOut(BaseModel):
    key: str
    label: str
    price: float
    market_open: bool
    source: str
    tradingsymbol: str = ""
    price_type: str = "LTP"
    error: str | None = None


class WindowLegOut(BaseModel):
    side: str
    strike: float
    premium_close: float = 0
    entry_pct: float | None = None
    entry_price: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    tradable: bool = False
    skip_reason: str | None = None


class WindowOut(BaseModel):
    index: int
    start_hhmm: str
    reference_close: float | None = None
    ce: WindowLegOut | None = None
    pe: WindowLegOut | None = None


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
    tp: float | None = None
    trading_mode: str
    trading_symbol: str | None = None
    entry_time: str | None = None


class CompletedPositionOut(BaseModel):
    id: int
    leg_id: str
    side: str
    strike: float
    entry_price: float
    exit_price: float | None
    pnl: float | None
    exit_reason: str | None
    trading_mode: str
    trading_symbol: str | None = None
    entry_time: str | None = None
    exit_time: str | None = None


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
    message: str | None = None


class DashboardOut(BaseModel):
    sensex_price: float
    sensex_market_open: bool
    sensex_source: str
    sensex_error: str | None = None
    algo_running: bool
    trading_mode: str
    config: dict[str, Any]
    expiry_info: dict[str, Any] = {}
    windows: list[WindowOut]
    realized_pnl: float
    unrealized_pnl: float
    active_trades: list[ActivePositionOut]
    completed_trades: list[CompletedPositionOut]
    logs: list[TradingLogOut]


class BreakoutBacktestRunIn(BaseModel):
    fromDate: str
    toDate: str
    config: dict[str, Any] | None = None


class BreakoutBacktestOut(BaseModel):
    ok: bool
    message: str
    fromDate: str
    toDate: str
    daysRun: int
    skippedDays: int
    skippedDates: list[str] = []
    summary: dict[str, Any]
    analysis: dict[str, Any] = {}
    daySummaries: list[dict[str, Any]]
    dayDetails: list[dict[str, Any]] = []
    trades: list[dict[str, Any]]
    tradeRecords: list[dict[str, Any]] = []
    candles: list[dict[str, Any]]
    chartSeries: list[dict[str, Any]] = []
    chartTrades: list[dict[str, Any]]
    config: dict[str, Any]
    windows: list[dict[str, Any]] = []
    sessionError: str | None = None
    failedDays: int = 0
    debugRows: list[dict[str, Any]] = []
    stocksRinAuth: dict[str, Any] = {}
    dataSource: str | None = None

    model_config = {"extra": "ignore"}
