export type MarketKey =
  | "CRUDE_OIL"
  | "CRUDE_OIL_MINI"
  | "CRUDE_OIL_MEGA"
  | "NATURAL_GAS"
  | "NATURAL_GAS_MINI"
  | "NATURAL_GAS_MEGA"
  | "SILVER_MICRO"
  | "SILVER_MINI";
export type TradingMode = "PAPER" | "LIVE";

export type Strategy2Config = {
  startTime: string;
  endTime: string;
  market: MarketKey;
  referencePrice: number;
  initialLots: number;
  gridGap: number;
  gridLevelsAbove: number;
  gridLevelsBelow: number;
  lotsPerGrid: number;
  invertGrid: boolean;
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

export type GridLevelRow = {
  level: string;
  price: number;
  action: string;
  status?: string;
};

export type GridBacktestCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  date?: string;
};

export type GridBacktestTrade = {
  id: number;
  date: string;
  time: string;
  action: string;
  level: string;
  lotsDelta: number;
  side: "BUY" | "SELL";
  lots: number;
  /** Configured grid trigger price (e.g. 300 BASE, 298 D1) */
  levelPrice: number;
  /** Actual candle/market price when the action fired */
  fillPrice: number;
  price: number;
  entryPrice?: number | null;
  exitPrice?: number | null;
  gridEntryPrice?: number | null;
  gridExitPrice?: number | null;
  positionAfter: number;
  realizedPnl: number;
  message: string;
  symbol: string;
};

export type GridBacktestDaySummary = {
  date: string;
  trades: number;
  pnl: number;
  endPositionLots: number;
  candles: number;
};

export type GridBacktestResult = {
  ok: boolean;
  message: string;
  instrument: string;
  market: string;
  fromDate: string;
  toDate: string;
  daysRun: number;
  skippedDays: number;
  skippedDates?: string[];
  summary: {
    totalTrades: number;
    totalPnl: number;
    finalPositionLots: number;
    maxLots: number;
    winDays: number;
    lossDays: number;
    netDays: number;
  };
  gridLevels: GridLevelRow[];
  daySummaries: GridBacktestDaySummary[];
  trades: GridBacktestTrade[];
  candles: GridBacktestCandle[];
  chartTrades: GridBacktestTrade[];
  chartSubtitle: string;
  referencePrice: number;
};

export type GridBacktestParams = Strategy2Config & {
  fromDate: string;
  toDate: string;
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
  grid_levels: GridLevelRow[];
  reference_price: number;
  position_lots: number;
  realized_pnl: number;
  unrealized_pnl: number;
  current_market_price: number;
  next_action_level?: string | null;
  active_trades: ActiveTrade[];
  completed_trades: CompletedTrade[];
  logs: TradingLogRow[];
  last_live_error?: string | null;
  last_live_error_at?: string | null;
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
  next_action_level: null,
  active_trades: [],
  completed_trades: [],
  logs: [],
  last_live_error: null,
  last_live_error_at: null,
};

export const EMPTY_CONFIG: Strategy2Config = {
  startTime: "09:00",
  endTime: "23:30",
  market: "CRUDE_OIL",
  referencePrice: 0,
  initialLots: 0,
  gridGap: 0,
  gridLevelsAbove: 0,
  gridLevelsBelow: 0,
  lotsPerGrid: 0,
  invertGrid: false,
};

/** Defaults for backtest only — not tied to live Strategy Settings. */
export const DEFAULT_BACKTEST_CONFIG: Strategy2Config = {
  startTime: "09:00",
  endTime: "23:30",
  market: "NATURAL_GAS",
  referencePrice: 0,
  initialLots: 10,
  gridGap: 2,
  gridLevelsAbove: 3,
  gridLevelsBelow: 3,
  lotsPerGrid: 2,
  invertGrid: false,
};

const BACKTEST_STORAGE_KEY = "strategy2_backtest_config";

export function loadBacktestConfig(): Strategy2Config {
  if (typeof window === "undefined") return { ...DEFAULT_BACKTEST_CONFIG };
  try {
    const raw = sessionStorage.getItem(BACKTEST_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_BACKTEST_CONFIG };
    const parsed = JSON.parse(raw) as Partial<Strategy2Config>;
    return { ...DEFAULT_BACKTEST_CONFIG, ...parsed };
  } catch {
    return { ...DEFAULT_BACKTEST_CONFIG };
  }
}

export function saveBacktestConfig(cfg: Strategy2Config) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(BACKTEST_STORAGE_KEY, JSON.stringify(cfg));
  } catch {
    /* ignore quota errors */
  }
}

export function configFromApi(raw: Record<string, unknown>): Strategy2Config {
  return {
    startTime: String(raw.startTime ?? "09:00"),
    endTime: String(raw.endTime ?? "23:30"),
    market: (raw.market as MarketKey) || "CRUDE_OIL",
    referencePrice: Number(raw.referencePrice ?? 0) || 0,
    initialLots: Number(raw.initialLots ?? 0) || 0,
    gridGap: Number(raw.gridGap ?? 0) || 0,
    gridLevelsAbove: Number(raw.gridLevelsAbove ?? 0) || 0,
    gridLevelsBelow: Number(raw.gridLevelsBelow ?? 0) || 0,
    lotsPerGrid: Number(raw.lotsPerGrid ?? 0) || 0,
    invertGrid: raw.invertGrid === true || String(raw.invertGrid).toLowerCase() === "true",
  };
}

export function configToApi(cfg: Strategy2Config): Record<string, unknown> {
  return { ...cfg };
}
