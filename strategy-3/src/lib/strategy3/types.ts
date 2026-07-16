export type TradingMode = "PAPER" | "LIVE";
export type ProductType = "MIS" | "NRML";

export type PremiumTier = {
  maxPremium: number;
  entryPercent: number;
};

export const DEFAULT_PREMIUM_TIERS: PremiumTier[] = [
  { maxPremium: 25, entryPercent: 65 },
  { maxPremium: 35, entryPercent: 55 },
  { maxPremium: 50, entryPercent: 45 },
  { maxPremium: 75, entryPercent: 35 },
  { maxPremium: 100, entryPercent: 30 },
  { maxPremium: 125, entryPercent: 22 },
];

export type ExpiryInfo = {
  referenceDate: string;
  currentWeekExpiryDate: string | null;
  currentWeekExpiryLabel: string;
  nextExpiryDate: string | null;
  nextExpiryLabel: string;
  knownExpiryDates: string[];
  source: string;
  autoDetected: boolean;
};

export type Strategy3Config = {
  startTime: string;
  windowCount: number;
  windowGapMinutes: number;
  candleTimeframeMinutes: number;
  targetPercent: number;
  stopLossPercent: number;
  quantity: number;
  productType: ProductType;
  expiryDayOnly: boolean;
  premiumTiers: PremiumTier[];
};

export const DEFAULT_CONFIG: Strategy3Config = {
  startTime: "14:35",
  windowCount: 3,
  windowGapMinutes: 10,
  candleTimeframeMinutes: 10,
  targetPercent: 25,
  stopLossPercent: 30,
  quantity: 1,
  productType: "MIS",
  expiryDayOnly: true,
  premiumTiers: DEFAULT_PREMIUM_TIERS.map((t) => ({ ...t })),
};

const STORAGE_KEY = "strategy3-config-v1";
const BACKTEST_STORAGE_KEY = "strategy3-backtest-config-v1";

function mergePremiumTiers(raw: unknown): PremiumTier[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return DEFAULT_PREMIUM_TIERS.map((t) => ({ ...t }));
  }
  const out: PremiumTier[] = [];
  for (let i = 0; i < raw.length; i++) {
    const row = raw[i];
    const fallback = DEFAULT_PREMIUM_TIERS[i] ?? DEFAULT_PREMIUM_TIERS[DEFAULT_PREMIUM_TIERS.length - 1];
    if (!row || typeof row !== "object") {
      out.push({ ...fallback });
      continue;
    }
    const r = row as Record<string, unknown>;
    out.push({
      maxPremium: Number(r.maxPremium ?? fallback.maxPremium),
      entryPercent: Number(r.entryPercent ?? fallback.entryPercent),
    });
  }
  return out.length ? out : DEFAULT_PREMIUM_TIERS.map((t) => ({ ...t }));
}

export function premiumTierLabel(tiers: PremiumTier[], index: number): string {
  const tier = tiers[index];
  if (!tier) return "—";
  if (index === 0) return `≤ ${tier.maxPremium}`;
  const prev = tiers[index - 1]?.maxPremium ?? 0;
  return `> ${prev} to ≤ ${tier.maxPremium}`;
}

export function loadConfig(): Strategy3Config {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CONFIG;
    return configFromApi(JSON.parse(raw) as Record<string, unknown>);
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function saveConfig(cfg: Strategy3Config) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

export function loadBacktestConfig(): Strategy3Config {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(BACKTEST_STORAGE_KEY);
    if (!raw) return loadConfig();
    return configFromApi(JSON.parse(raw) as Record<string, unknown>);
  } catch {
    return loadConfig();
  }
}

export function saveBacktestConfig(cfg: Strategy3Config) {
  if (typeof window === "undefined") return;
  localStorage.setItem(BACKTEST_STORAGE_KEY, JSON.stringify(cfg));
}

export function configFromApi(raw: Record<string, unknown>): Strategy3Config {
  return {
    ...DEFAULT_CONFIG,
    startTime: String(raw.startTime ?? DEFAULT_CONFIG.startTime),
    windowCount: Number(raw.windowCount ?? DEFAULT_CONFIG.windowCount),
    windowGapMinutes: Number(raw.windowGapMinutes ?? DEFAULT_CONFIG.windowGapMinutes),
    candleTimeframeMinutes: Number(raw.candleTimeframeMinutes ?? DEFAULT_CONFIG.candleTimeframeMinutes),
    targetPercent: Number(raw.targetPercent ?? DEFAULT_CONFIG.targetPercent),
    stopLossPercent: Number(raw.stopLossPercent ?? DEFAULT_CONFIG.stopLossPercent),
    quantity: Number(raw.quantity ?? DEFAULT_CONFIG.quantity),
    productType: (raw.productType as ProductType) || DEFAULT_CONFIG.productType,
    expiryDayOnly: raw.expiryDayOnly !== false,
    premiumTiers: mergePremiumTiers(raw.premiumTiers),
  };
}

export function configToApi(cfg: Strategy3Config): Record<string, unknown> {
  return {
    startTime: cfg.startTime,
    windowCount: cfg.windowCount,
    windowGapMinutes: cfg.windowGapMinutes,
    candleTimeframeMinutes: cfg.candleTimeframeMinutes,
    targetPercent: cfg.targetPercent,
    stopLossPercent: cfg.stopLossPercent,
    quantity: cfg.quantity,
    productType: cfg.productType,
    expiryDayOnly: cfg.expiryDayOnly,
    premiumTiers: cfg.premiumTiers.map((t) => ({
      maxPremium: t.maxPremium,
      entryPercent: t.entryPercent,
    })),
  };
}

export function windowTimes(cfg: Strategy3Config): string[] {
  const [hh, mm] = cfg.startTime.split(":").map((x) => parseInt(x, 10) || 0);
  const out: string[] = [];
  for (let i = 0; i < cfg.windowCount; i++) {
    const total = hh * 60 + mm + i * cfg.windowGapMinutes;
    out.push(`${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`);
  }
  return out;
}

export type WindowLeg = {
  side: string;
  strike: number;
  premium_close?: number;
  entry_pct?: number | null;
  entry_price?: number | null;
  target_price?: number | null;
  stop_price?: number | null;
  tradable?: boolean;
  skip_reason?: string | null;
};

export type WindowRow = {
  index: number;
  start_hhmm: string;
  reference_close?: number | null;
  ce?: WindowLeg | null;
  pe?: WindowLeg | null;
};

export type DashboardSnapshot = {
  sensex_price: number;
  sensex_market_open: boolean;
  sensex_source: string;
  sensex_error?: string | null;
  algo_running: boolean;
  trading_mode: TradingMode;
  config: Record<string, unknown>;
  expiry_info?: ExpiryInfo;
  windows: WindowRow[];
  realized_pnl: number;
  unrealized_pnl: number;
  today_realized_pnl?: number;
  today_pnl?: number;
  active_trades: Array<{
    id: number;
    leg_id: string;
    side: string;
    strike: number;
    lots: number;
    quantity: number;
    entry_price: number;
    current_price: number;
    pnl: number;
    tp?: number | null;
    trading_mode: string;
    trading_symbol?: string | null;
    entry_time?: string | null;
  }>;
  completed_trades: Array<{
    id: number;
    leg_id: string;
    side: string;
    strike: number;
    entry_price: number;
    exit_price?: number | null;
    pnl?: number | null;
    exit_reason?: string | null;
    trading_mode: string;
    trading_symbol?: string | null;
    entry_time?: string | null;
    exit_time?: string | null;
  }>;
  logs: Array<{
    id: number;
    created_at: string;
    mode: string;
    leg: string;
    action: string;
    symbol?: string | null;
    strike?: number | null;
    quantity?: number | null;
    entry_price?: number | null;
    exit_price?: number | null;
    pnl?: number | null;
    status?: string | null;
    message?: string | null;
  }>;
};

export const EMPTY_DASHBOARD: DashboardSnapshot = {
  sensex_price: 0,
  sensex_market_open: false,
  sensex_source: "",
  algo_running: false,
  trading_mode: "PAPER",
  config: {},
  windows: [],
  realized_pnl: 0,
  unrealized_pnl: 0,
  active_trades: [],
  completed_trades: [],
  logs: [],
};

export type BreakoutBacktestCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  date?: string;
};

export type BreakoutBacktestTrade = {
  id: number;
  serialNo?: number;
  date: string;
  window?: string;
  side: string;
  sideLabel?: string;
  strike?: number;
  referenceClose?: number;
  reference?: number;
  premiumClose?: number;
  entryPct?: number;
  triggerPrice?: number;
  entryPrice?: number;
  targetPrice?: number;
  stopPrice?: number;
  entryTime?: string;
  exitTimeFormatted?: string;
  exitPrice?: number;
  status?: string;
  exitReason?: string;
  pnl?: number;
  points?: number;
  lots?: number;
  sizeMultiplier?: number;
  effectiveQuantity?: number;
  message?: string;
  details?: string;
  symbol?: string;
  fillTime?: string;
  exitTime?: string;
  historicalToken?: string;
  tradeDuration?: number | null;
  tradeDurationMinutes?: number | null;
  entryPremium?: number | null;
  expiry?: string;
  optionSymbol?: string;
  chartId?: string;
  highestPremiumAfterEntry?: number | null;
  lowestPremiumAfterEntry?: number | null;
  highestPremiumDuringMonitoring?: number | null;
  entryTriggerPrice?: number | null;
  triggerCandleHigh?: number | null;
  triggerCandleLow?: number | null;
  lastCandleClose?: number | null;
  referenceCandleEnd?: string;
  monitoringStartsAt?: string;
  totalSessionCandles?: number;
  monitorCandlesAfterRef?: number;
};

export type BreakoutLegSetup = {
  strike: number;
  premiumClose: number;
  entryPct?: number | null;
  triggerPrice?: number | null;
  targetPrice?: number | null;
  stopPrice?: number | null;
  tradable: boolean;
  skipReason?: string | null;
  symbol?: string;
};

export type BreakoutWindowSetup = {
  window: string;
  referenceClose: number;
  referenceTime: string;
  ce: BreakoutLegSetup;
  pe: BreakoutLegSetup;
};

export type BreakoutChartSeries = {
  id: string;
  date: string;
  window: string;
  side: string;
  sideLabel: string;
  strike: number;
  symbol: string;
  referenceClose: number;
  candles: BreakoutBacktestCandle[];
  levels: {
    premiumClose?: number;
    trigger?: number | null;
    target?: number | null;
    stop?: number | null;
  };
};

export type BreakoutAnalysis = {
  tpHits: number;
  slHits: number;
  eodExits: number;
  pending: number;
  noTrade: number;
  tokenNotFound?: number;
  dataErrors?: number;
  skipped: number;
  totalPoints: number;
  totalPnl: number;
  winTrades: number;
  lossTrades: number;
  breakevenTrades: number;
  grossProfit: number;
  grossLoss: number;
  closedTrades: number;
  expiryDays: number;
};

export type BreakoutDebugRow = {
  date: string;
  window: string;
  side: string;
  referenceTime?: string;
  referenceClose?: number | null;
  expiry?: string;
  strike?: number;
  expectedSymbol?: string;
  actualSymbol?: string;
  resolvedSymbol?: string;
  token?: string;
  resolvedHistoricalToken?: string;
  historicalCandleCount?: number;
  totalSessionCandles?: number;
  monitorCandlesAfterRef?: number;
  referenceCandleStart?: string;
  referenceCandleEnd?: string;
  monitoringStartsAt?: string;
  entryTriggerPrice?: number | null;
  triggerCandleHigh?: number | null;
  triggerCandleLow?: number | null;
  highestPremiumAfterEntry?: number | null;
  lowestPremiumAfterEntry?: number | null;
  highestPremiumDuringMonitoring?: number | null;
  lastCandleClose?: number | null;
  noLookAhead?: boolean;
  referencePrice?: number | null;
  triggerPrice?: number | null;
  targetPrice?: number | null;
  stopPrice?: number | null;
  exitCandleTime?: string | null;
  exitReason?: string | null;
  optionCandleTime?: string;
  optionOpen?: number | null;
  optionHigh?: number | null;
  optionLow?: number | null;
  optionClose?: number | null;
  premiumClose?: number | null;
  intrinsic?: number | null;
  entryPct?: number | null;
  entryPrice?: number | null;
  triggerFound?: boolean | null;
  triggerCandleTime?: string | null;
  status: string;
  reason: string;
};

export type BreakoutDayDetail = {
  date: string;
  pnl: number;
  setups: BreakoutWindowSetup[];
  chartSeries: BreakoutChartSeries[];
  error?: string;
  candleDebug?: Record<string, unknown>;
};

export type BreakoutBacktestResult = {
  ok: boolean;
  message: string;
  fromDate: string;
  toDate: string;
  daysRun: number;
  failedDays?: number;
  skippedDays: number;
  skippedDates?: string[];
  summary: {
    totalTrades: number;
    totalPnl: number;
    winDays: number;
    lossDays: number;
    netDays: number;
  };
  analysis?: BreakoutAnalysis;
  daySummaries: Array<{ date: string; trades: number; pnl: number; candles?: number; error?: string; failed?: boolean; candleDebug?: Record<string, unknown> }>;
  dayDetails?: BreakoutDayDetail[];
  trades: BreakoutBacktestTrade[];
  tradeRecords?: BreakoutBacktestTrade[];
  candles: BreakoutBacktestCandle[];
  chartSeries?: BreakoutChartSeries[];
  debugRows?: BreakoutDebugRow[];
  dataSource?: string;
  sessionError?: string | null;
  chartTrades: BreakoutBacktestTrade[];
  config: Record<string, unknown>;
  windows?: Array<{ index: number; start_hhmm: string }>;
};

export type BreakoutBacktestParams = {
  fromDate: string;
  toDate: string;
  config: Record<string, unknown>;
};
