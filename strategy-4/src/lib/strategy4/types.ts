export type MarketKey = "CRUDE_OIL" | "NATURAL_GAS" | "SILVER_MICRO";
export type TradingMode = "PAPER" | "LIVE";

export type Strategy4Config = {
  startTime: string;
  endTime: string;
  market: MarketKey;
  lotSize: number;
  breakoutDistance: number;
  takeProfit: number;
  stopLoss: number;
};

export type MarketQuote = {
  key: string;
  label: string;
  price: number;
  market_open: boolean;
  source: string;
  tradingsymbol: string;
  price_type?: string;
  error?: string | null;
};

export type StrategyLevelRow = {
  level: string;
  price: number;
  action?: string;
  status?: string;
  kind?: string;
  label?: string;
  id?: number;
};

export type BreakoutRoundTrip = {
  id: number;
  date: string;
  tradeLabel: string;
  entryType: string;
  side: string;
  entryPrice: number;
  tpPrice?: number;
  slPrice?: number;
  exitPrice: number;
  exitReason: string;
  tradePnl: number;
  runningDayPnl: number;
  entryTime?: string;
  exitTime?: string;
  entryTimeLabel?: string;
  exitTimeLabel?: string;
  durationMinutes?: number | null;
  lots: number;
  symbol?: string;
};

export type DailyReferenceRow = {
  date: string;
  referenceClose: number;
  referenceOpen?: number;
  referenceHigh?: number;
  referenceLow?: number;
  referenceCandleTime: string;
  buyTrigger: number;
  sellTrigger: number;
  buyTriggerTime: string;
  sellTriggerTime: string;
  buyTriggerTouchHigh?: number | null;
  sellTriggerTouchLow?: number | null;
  firstTriggerSide: string;
  initialDirection: string;
  initialTriggerTime: string;
  result: string;
  pnl?: number;
  phase?: string;
  sameBarNotes?: string[];
};

export type DailyTimelineStep = {
  time: string;
  label: string;
  detail: string;
};

export type DailyChartPack = {
  date: string;
  candles: BreakoutBacktestCandle[];
  trades: BreakoutBacktestTrade[];
  roundTrips: BreakoutRoundTrip[];
  levels: StrategyLevelRow[];
  timeline: DailyTimelineStep[];
  referenceClose?: number;
  result?: string;
};

export type BreakoutBacktestTrade = {
  id: number;
  date: string;
  time: string;
  action: string;
  side: "BUY" | "SELL";
  lots: number;
  fillPrice: number;
  entryPrice?: number | null;
  exitPrice?: number | null;
  tpPrice?: number | null;
  slPrice?: number | null;
  isReverse?: boolean;
  entryType?: string | null;
  exitReason?: string | null;
  tradePnl?: number | null;
  runningDayPnl?: number | null;
  realizedPnl: number;
  message: string;
  symbol: string;
  sameBarAmbiguity?: boolean;
};

export type BreakoutBacktestDaySummary = {
  date: string;
  trades: number;
  events?: number;
  pnl: number;
  phase?: string;
  referencePrice?: number;
  result?: string;
  candles: number;
};

export type BreakoutBacktestSummary = {
  totalTradingDays: number;
  totalCalendarDays: number;
  skippedDays: number;
  totalTrades: number;
  totalPnl: number;
  buyTrades: number;
  sellTrades: number;
  reverseTrades: number;
  winningInitialTrades: number;
  losingInitialTrades: number;
  winningReverseTrades: number;
  losingReverseTrades: number;
  breakevenInitialTrades?: number;
  breakevenReverseTrades?: number;
  winRate: number;
  averageWin: number;
  averageLoss: number;
  profitFactor: number;
  maxDrawdown: number;
  expectancy: number;
  averageTradeDurationMinutes: number;
  winDays: number;
  lossDays: number;
  netDays: number;
};

export type BreakoutBacktestResult = {
  ok: boolean;
  message: string;
  instrument: string;
  market: string;
  fromDate: string;
  toDate: string;
  daysRun: number;
  skippedDays: number;
  skippedDates?: string[];
  summary: BreakoutBacktestSummary;
  executionPolicy?: Record<string, string>;
  dailyReference: DailyReferenceRow[];
  dailyCharts: DailyChartPack[];
  strategyLevels: StrategyLevelRow[];
  daySummaries: BreakoutBacktestDaySummary[];
  trades: BreakoutBacktestTrade[];
  roundTrips: BreakoutRoundTrip[];
  candles: BreakoutBacktestCandle[];
  chartTrades: BreakoutBacktestTrade[];
  chartLevels?: StrategyLevelRow[];
  chartSubtitle: string;
  referencePrice: number;
};

export type BreakoutBacktestParams = Strategy4Config & {
  fromDate: string;
  toDate: string;
};

export type BreakoutBacktestCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  date?: string;
};

export type ActiveTrade = {
  id: number;
  leg_id: string;
  side: string;
  lots: number;
  quantity: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  status: string;
  trading_mode: string;
  entry_time?: string | null;
};

export type CompletedTrade = {
  id: number;
  entry_time?: string | null;
  exit_time?: string | null;
  leg_id: string;
  side?: string | null;
  tp?: number | null;
  sl?: number | null;
  lots?: number | null;
  symbol?: string | null;
  entry_price?: number | null;
  exit_price?: number | null;
  pnl?: number | null;
  trading_mode: string;
  exit_reason?: string | null;
};

export type TradingLogRow = {
  id: number;
  created_at: string;
  mode: string;
  leg: string;
  action: string;
  symbol?: string | null;
  quantity?: number | null;
  pnl?: number | null;
  message?: string | null;
};

export type DashboardSnapshot = {
  config: Record<string, unknown>;
  algo_running: boolean;
  trading_mode: TradingMode;
  quotes: MarketQuote[];
  grid_levels: StrategyLevelRow[];
  reference_price: number;
  position_lots: number;
  realized_pnl: number;
  unrealized_pnl: number;
  today_realized_pnl?: number;
  today_pnl?: number;
  current_market_price: number;
  next_action_level?: string | null;
  phase?: string;
  buy_trigger?: number;
  sell_trigger?: number;
  entry_price?: number;
  tp_price?: number;
  sl_price?: number;
  trade_count?: number;
  status_message?: string;
  market?: string;
  active_symbol?: string;
  active_side?: string | null;
  is_reverse?: boolean;
  ref_candle_time?: string;
  session_start?: string;
  session_end?: string;
  breakout_distance?: number;
  take_profit_pts?: number;
  stop_loss_pts?: number;
  lots?: number;
  price_type?: string;
  in_session?: boolean;
  last_live_error?: string | null;
  last_live_error_at?: string | null;
  active_trades: ActiveTrade[];
  completed_trades: CompletedTrade[];
  logs: TradingLogRow[];
};

export const EMPTY_DASHBOARD: DashboardSnapshot = {
  config: {},
  algo_running: false,
  trading_mode: "PAPER",
  quotes: [],
  grid_levels: [],
  reference_price: 0,
  position_lots: 0,
  realized_pnl: 0,
  unrealized_pnl: 0,
  current_market_price: 0,
  active_trades: [],
  completed_trades: [],
  logs: [],
};

export const EMPTY_CONFIG: Strategy4Config = {
  startTime: "18:29",
  endTime: "23:30",
  market: "CRUDE_OIL",
  lotSize: 4,
  breakoutDistance: 0.5,
  takeProfit: 1.0,
  stopLoss: 0.8,
};

export const DEFAULT_BACKTEST_CONFIG: Strategy4Config = {
  startTime: "18:29",
  endTime: "23:30",
  market: "NATURAL_GAS",
  lotSize: 4,
  breakoutDistance: 0.5,
  takeProfit: 1.0,
  stopLoss: 0.8,
};

const BACKTEST_STORAGE_KEY = "strategy4_backtest_config";

export function loadBacktestConfig(): Strategy4Config {
  if (typeof window === "undefined") return { ...DEFAULT_BACKTEST_CONFIG };
  try {
    const raw = sessionStorage.getItem(BACKTEST_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_BACKTEST_CONFIG };
    const parsed = JSON.parse(raw) as Partial<Strategy4Config>;
    return { ...DEFAULT_BACKTEST_CONFIG, ...parsed };
  } catch {
    return { ...DEFAULT_BACKTEST_CONFIG };
  }
}

export function saveBacktestConfig(cfg: Strategy4Config) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(BACKTEST_STORAGE_KEY, JSON.stringify(cfg));
  } catch {
    /* ignore */
  }
}

export function configFromApi(raw: Record<string, unknown>): Strategy4Config {
  return {
    startTime: String(raw.startTime ?? "18:29"),
    endTime: String(raw.endTime ?? "23:30"),
    market: (raw.market as MarketKey) || "CRUDE_OIL",
    lotSize: Number(raw.lotSize ?? raw.lots ?? raw.initialLots ?? 4) || 4,
    breakoutDistance: Number(raw.breakoutDistance ?? 0.5) || 0.5,
    takeProfit: Number(raw.takeProfit ?? 1) || 1,
    stopLoss: Number(raw.stopLoss ?? 0.8) || 0.8,
  };
}

export function configToApi(cfg: Strategy4Config): Record<string, unknown> {
  return { ...cfg };
}

/** @deprecated use StrategyLevelRow */
export type GridLevelRow = StrategyLevelRow;
/** @deprecated use BreakoutBacktestTrade */
export type GridBacktestTrade = BreakoutBacktestTrade;
/** @deprecated use BreakoutBacktestCandle */
export type GridBacktestCandle = BreakoutBacktestCandle;
/** @deprecated use BreakoutBacktestResult */
export type GridBacktestResult = BreakoutBacktestResult;
/** @deprecated use BreakoutBacktestParams */
export type GridBacktestParams = BreakoutBacktestParams;
