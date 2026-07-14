'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from 'react';
import { usePathname } from 'next/navigation';

import { normalizeLegEntryMode, useAlgoRuntime } from '@/components/trader/app-shell';
import { defaultEntryLots, normalizeEntryLots } from '@/lib/backtest-trend-analysis';
import { getApiBase, getStoredToken } from '@/lib/auth';
import { isAngelTokenErrorText, refreshAngelSession } from '@/lib/angel-session';

type AngelRow = Record<string, unknown>;

type AngelLive = {
  angel_ok?: boolean;
  angel_message?: string;
  mode?: string;
  fetched?: AngelRow[];
  unfetched?: AngelRow[];
  as_of?: number;
  token_expired?: boolean;
  quote_source?: string;
  price_type?: string;
  market_open?: boolean;
};

type StartBarClose = {
  ok?: boolean;
  start_time?: string;
  close?: number | null;
  candle_time?: string | null;
  date?: string | null;
  is_fallback?: boolean;
  message?: string;
};

type TradingMode = 'PAPER' | 'LIVE';

type ApiLogRow = {
  id: number;
  created_at: string;
  mode: string;
  leg: string;
  action: string;
  symbol: string | null;
  strike: number | null;
  quantity: number | null;
  entry_price: number | null;
  exit_price: number | null;
  pnl: number | null;
  status: string | null;
  order_id: string | null;
  message: string | null;
};

type ApiActiveRow = {
  id: number;
  leg_id: string;
  side: string;
  strike: number;
  lots: number;
  quantity: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  status: string;
  trading_mode: string;
  entry_time: string | null;
  symbol: string | null;
  index_entry: number | null;
  tp1_level: number | null;
  tp2_trail_level: number | null;
  sl_level: number | null;
  tp1_hit: boolean;
  order_id: string | null;
  last_order_message: string | null;
};

type ApiCompletedRow = {
  id: number;
  entry_time: string | null;
  exit_time: string | null;
  leg_id: string;
  side: string | null;
  range_level: number | null;
  strike: number | null;
  tp: number | null;
  symbol: string | null;
  entry_price: number | null;
  exit_price: number | null;
  pnl: number | null;
  trading_mode: string;
  exit_reason: string | null;
  lots: number | null;
};

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function pickAngelQuoteRow(rows: AngelRow[] | undefined): AngelRow | undefined {
  if (!rows?.length) return undefined;
  const tokenOf = (r: AngelRow) => {
    const t = r.symbolToken ?? (r as { symboltoken?: unknown }).symboltoken;
    if (t === undefined || t === null) return '';
    return String(t).trim();
  };
  const symOf = (r: AngelRow) =>
    String(r.tradingSymbol ?? (r as { symbol?: unknown }).symbol ?? '').toUpperCase();
  const isIndexSensex = (r: AngelRow) => {
    if (tokenOf(r) === '99919000') return true;
    const s = symOf(r);
    if (s === 'SENSEX') return true;
    return false;
  };
  const isLikelyEtf = (r: AngelRow) => /ETF|BEES|IETF|BETA|ADD$/i.test(symOf(r));
  const sensex = rows.find((r) => isIndexSensex(r) && !isLikelyEtf(r));
  return sensex ?? rows[0];
}

/** Angel OHLC / FULL payloads use different keys; pick first usable price. */
function quotePriceFromRow(row: AngelRow | undefined): number | null {
  if (!row) return null;
  const keys = [
    'ltp',
    'Ltp',
    'lasttradedprice',
    'lastTradePrice',
    'close',
    'Close',
    'open',
    'Open',
    'netPrice',
    'NetPrice',
  ];
  for (const k of keys) {
    const n = num((row as Record<string, unknown>)[k]);
    if (n != null && n > 0) return n;
  }
  return null;
}

function pctFromRow(row: AngelRow | undefined): number | null {
  if (!row) return null;
  const keys = ['percentChange', 'pChange', 'percentage'];
  for (const k of keys) {
    const n = num((row as Record<string, unknown>)[k]);
    if (n != null && Number.isFinite(n)) return n;
  }
  return null;
}

function netFromRow(row: AngelRow | undefined): number | null {
  if (!row) return null;
  const keys = ['netChange', 'priceChange', 'change'];
  for (const k of keys) {
    const n = num((row as Record<string, unknown>)[k]);
    if (n != null && Number.isFinite(n)) return n;
  }
  return null;
}

function httpErrorDetail(data: Record<string, unknown>, fallback: string): string {
  const d = data.detail;
  if (typeof d === 'string' && d.trim()) return d;
  if (Array.isArray(d) && d.length) {
    const first = d[0] as Record<string, unknown>;
    if (typeof first.msg === 'string') return first.msg;
    if (typeof first.message === 'string') return first.message;
  }
  return fallback;
}

function fmtInr(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function roundPx(n: number): number {
  return Math.round(n * 100) / 100;
}

function clampNumEntries(n: number): number {
  return Math.min(20, Math.max(1, Math.round(n)));
}

function syncExitLotsToEngine(
  tp1: number,
  tp2: number,
  setLotsPerEntry: (n: number) => void,
  setNumEntries: (n: number) => void,
  setPartialClosePercent: (n: number) => void,
) {
  const t1 = Math.max(1, Math.round(tp1));
  const t2 = Math.max(1, Math.round(tp2));
  const total = t1 + t2;
  setLotsPerEntry(total);
  setNumEntries(1);
  setPartialClosePercent(Math.min(99, Math.max(1, Math.round((t1 / total) * 100))));
  return { tp1: t1, tp2: t2 };
}

function defaultTargetArrays(
  base: number,
  entryGap: number,
  addGap: number,
  numEntries: number,
  t1p: number,
  t2p: number
): { ceT1: number[]; ceT2: number[]; peT1: number[]; peT2: number[] } {
  const n = clampNumEntries(numEntries);
  const ceT1: number[] = [];
  const ceT2: number[] = [];
  let ce = base + entryGap;
  for (let i = 0; i < n; i++) {
    if (i > 0) ce = roundPx(ce - addGap);
    ceT1.push(roundPx(ce + t1p));
    ceT2.push(roundPx(ce + t2p));
  }
  const peT1: number[] = [];
  const peT2: number[] = [];
  let pe = base - entryGap;
  for (let i = 0; i < n; i++) {
    if (i > 0) pe = roundPx(pe + addGap);
    peT1.push(roundPx(pe - t1p));
    peT2.push(roundPx(pe - t2p));
  }
  return { ceT1, ceT2, peT1, peT2 };
}

function parseNumArray(v: unknown): number[] | null {
  if (!Array.isArray(v)) return null;
  const out: number[] = [];
  for (const x of v) {
    const z = num(x);
    if (z == null || !Number.isFinite(z)) return null;
    out.push(z);
  }
  return out;
}

function setIfChanged<T>(setter: (value: T) => void, lastRef: MutableRefObject<string>, value: T) {
  const next = JSON.stringify(value);
  if (next === lastRef.current) return;
  lastRef.current = next;
  setter(value);
}

/** Default strategy numbers (engine `sensex_adaptive_trend.py` mirrors these). */
const DEFAULT_ENTRY_GAP = 191;
const DEFAULT_ADD_GAP = 45;
const DEFAULT_NUM_ENTRIES = 4;
const DEFAULT_TARGET1_PTS = 45;
const DEFAULT_FIRST_ENTRY_TP1_PTS = 70;
const DEFAULT_TARGET2_PTS = 30;
const DEFAULT_LOTS_PER_ENTRY = 2;
const DEFAULT_STRIKE_OFFSET = 200;
const DEFAULT_STOP_DISTANCE = 191;
const DEFAULT_ENTRY_LOTS = [2, 1, 1, 1];
const DEFAULT_INITIAL_LOTS = 2;
const DEFAULT_ADD_LOTS = 1;
const DEFAULT_TP2_TRAIL = 30;
const DEFAULT_RE_ENTRY_GAP = 70;
const DEFAULT_MAX_RE_ENTRIES = 3;

type PreviewLegRow = {
  leg: string;
  side: string;
  entry: number;
  target1: number;
  target2: number;
  lots: number;
  status: string;
  tone: 'ce' | 'pe';
  rowIdx: number;
};

function buildPreviewLegRows(
  base: number,
  entryGap: number,
  addGap: number,
  numEntries: number,
  lotsPerEntry: number,
  liveIndex: number | null,
  ceT1: number[],
  ceT2: number[],
  peT1: number[],
  peT2: number[]
): PreviewLegRow[] {
  const n = clampNumEntries(numEntries);
  const rows: PreviewLegRow[] = [];

  const statusFor = (tone: 'ce' | 'pe', entry: number): string => {
    if (liveIndex == null || !Number.isFinite(liveIndex)) return '—';
    if (tone === 'ce') return liveIndex >= entry ? 'At/above entry' : 'Below entry';
    return liveIndex <= entry ? 'At/below entry' : 'Above entry';
  };

  let ceEntry = base + entryGap;
  for (let i = 0; i < n; i++) {
    if (i > 0) ceEntry = roundPx(ceEntry - addGap);
    const entry = roundPx(ceEntry);
    rows.push({
      leg: `CE${i + 1}`,
      side: 'CE BUY',
      entry,
      target1: roundPx(ceT1[i] ?? entry),
      target2: roundPx(ceT2[i] ?? entry),
      lots: Math.max(1, lotsPerEntry),
      status: statusFor('ce', entry),
      tone: 'ce',
      rowIdx: i,
    });
  }

  let peEntry = base - entryGap;
  for (let i = 0; i < n; i++) {
    if (i > 0) peEntry = roundPx(peEntry + addGap);
    const entry = roundPx(peEntry);
    rows.push({
      leg: `PE${i + 1}`,
      side: 'PE BUY',
      entry,
      target1: roundPx(peT1[i] ?? entry),
      target2: roundPx(peT2[i] ?? entry),
      lots: Math.max(1, lotsPerEntry),
      status: statusFor('pe', entry),
      tone: 'pe',
      rowIdx: i,
    });
  }

  return rows;
}

function parseDbUtcIso(iso: string): Date {
  let s = iso.trim();
  if (!s) return new Date(NaN);
  if (s.includes(' ') && !s.includes('T')) s = s.replace(' ', 'T');
  const hasTz =
    /[zZ]$/.test(s) || /[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{2}\d{2}$/.test(s);
  if (!hasTz) {
    s = s.replace(/(\.\d{3})\d+/, '$1');
    s = `${s}Z`;
  }
  return new Date(s);
}

function formatLogTimestamp(iso: string): string {
  try {
    const d = parseDbUtcIso(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 19);
    return d.toLocaleString('en-GB', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return iso;
  }
}

/** Full date + time in India timezone for completed trades (entry / exit). */
function formatTradeTimeIST(iso: string | null | undefined): string {
  if (iso == null || iso === '') return '—';
  try {
    const d = parseDbUtcIso(iso);
    if (Number.isNaN(d.getTime())) return String(iso).replace('T', ' ').slice(0, 23);
    // Match trading-log style: DD/MM/YYYY HH:mm:ss IST (en-GB day-first, 24h).
    const s = d.toLocaleString('en-GB', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    return `${s} IST`;
  } catch {
    return String(iso).slice(0, 24);
  }
}

type TradingDashboardContextValue = ReturnType<typeof useTradingDashboardState>;

const TradingDashboardContext = createContext<TradingDashboardContextValue | null>(null);

export function useTradingDashboard() {
  const ctx = useContext(TradingDashboardContext);
  if (!ctx) {
    throw new Error('useTradingDashboard must be used within TradingDashboardProvider');
  }
  return ctx;
}

export function TradingDashboardProvider({ children }: { children: ReactNode }) {
  const value = useTradingDashboardState();
  return (
    <TradingDashboardContext.Provider value={value}>{children}</TradingDashboardContext.Provider>
  );
}

function useTradingDashboardState() {
  const pathname = usePathname();
  const isBacktestPage = pathname === '/backtest';
  const { algoEnabled, setAlgoEnabled, legEntryMode, setLegEntryMode } = useAlgoRuntime();
  const [referencePrice, setReferencePrice] = useState<number>(0);
  const [angel, setAngel] = useState<AngelLive | null>(null);
  const [angelErr, setAngelErr] = useState<string | null>(null);
  const [angelTokenExpired, setAngelTokenExpired] = useState(false);

  const [startBar, setStartBar] = useState<StartBarClose | null>(null);
  const [startBarErr, setStartBarErr] = useState<string | null>(null);
  const [startBarLoading, setStartBarLoading] = useState(false);

  const fetchAngel = useCallback(async () => {
    const token = getStoredToken();
    if (!token) return;
    if (quoteInFlightRef.current) return;
    quoteInFlightRef.current = true;
    try {
      const res = await fetch(`${getApiBase()}/angel/live-quote`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const detail = httpErrorDetail(data, `HTTP ${res.status}`);
        setAngelErr(detail);
        setAngelTokenExpired(isAngelTokenErrorText(detail) || res.status === 503);
        setAngel(null);
        return;
      }
      const nextAngel = {
        angel_ok: Boolean(data.angel_ok),
        angel_message: typeof data.angel_message === 'string' ? data.angel_message : '',
        mode: typeof data.mode === 'string' ? data.mode : '',
        fetched: Array.isArray(data.fetched) ? (data.fetched as AngelRow[]) : [],
        unfetched: Array.isArray(data.unfetched) ? (data.unfetched as AngelRow[]) : [],
        as_of: typeof data.as_of === 'number' ? data.as_of : undefined,
        token_expired: Boolean(data.token_expired),
        quote_source: typeof data.quote_source === 'string' ? data.quote_source : undefined,
        price_type: typeof data.price_type === 'string' ? data.price_type : undefined,
        market_open: typeof data.market_open === 'boolean' ? data.market_open : undefined,
      };
      const quotePx = quotePriceFromRow(pickAngelQuoteRow(nextAngel.fetched));
      const tokenErr =
        nextAngel.token_expired || isAngelTokenErrorText(nextAngel.angel_message);
      setAngelTokenExpired(tokenErr);
      if (tokenErr) {
        setAngelErr(nextAngel.angel_message || 'Angel SmartAPI token expired — regenerate to restore live price');
      } else if (!nextAngel.angel_ok && quotePx == null) {
        setAngelErr(nextAngel.angel_message || 'No SENSEX quote');
      } else {
        setAngelErr(null);
      }
      const nextAngelSig = JSON.stringify({ ...nextAngel, as_of: undefined });
      if (nextAngelSig !== angelSigRef.current) {
        angelSigRef.current = nextAngelSig;
        setAngel(nextAngel);
      }
    } catch {
      setAngelErr('Cannot reach Angel quote API — is the backend worker running?');
      setAngelTokenExpired(false);
      setAngel(null);
    } finally {
      quoteInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (isBacktestPage) return;
    const first = window.setTimeout(() => void fetchAngel(), 0);
    const id = window.setInterval(() => void fetchAngel(), 1000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [fetchAngel, isBacktestPage]);

  /** Live reference: prefer ltp/close/open from quote row (OHLC shapes vary). */
  useEffect(() => {
    const row = pickAngelQuoteRow(angel?.fetched);
    const px = quotePriceFromRow(row);
    if (px != null && Number.isFinite(px)) {
      setReferencePrice((prev) => (prev === px ? prev : px));
    }
  }, [angel]);

  const [startTime, setStartTime] = useState<string>('09:15');
  const [endTime, setEndTime] = useState<string>('15:30');
  const [referenceClose, setReferenceClose] = useState<number | null>(null);
  const [partialClosePercent, setPartialClosePercent] = useState<number>(50);
  const [tp1ExitLots, setTp1ExitLots] = useState(3);
  const [tp2ExitLots, setTp2ExitLots] = useState(3);
  const [firstEntryEnabled, setFirstEntryEnabled] = useState(true);
  const [adaptiveCallRetraceHigh, setAdaptiveCallRetraceHigh] = useState(100);
  const [adaptivePutRetraceHigh, setAdaptivePutRetraceHigh] = useState(190);
  const [adaptivePutRetraceLow, setAdaptivePutRetraceLow] = useState(100);
  const [adaptiveCallRetraceLow, setAdaptiveCallRetraceLow] = useState(190);
  const [slMode, setSlMode] = useState<'auto' | 'manual'>('auto');
  const [angelRefreshBusy, setAngelRefreshBusy] = useState(false);
  const [angelRefreshFeedback, setAngelRefreshFeedback] = useState<string | null>(null);

  const persistTimerRef = useRef<number | null>(null);
  const lastStartBarCloseRef = useRef<number | null>(null);
  const angelSigRef = useRef('');
  const quoteInFlightRef = useRef(false);
  const logsSigRef = useRef('');
  const activeSigRef = useRef('');
  const completedSigRef = useRef('');
  const completedClearPendingRef = useRef(false);
  const startBarSigRef = useRef('');

  const [tradingMode, setTradingMode] = useState<TradingMode>('PAPER');
  const [exchangeLotSize, setExchangeLotSize] = useState(20);
  const [entryGap, setEntryGap] = useState(DEFAULT_ENTRY_GAP);
  const [addGap, setAddGap] = useState(DEFAULT_ADD_GAP);
  const [numEntries, setNumEntries] = useState(DEFAULT_NUM_ENTRIES);
  const [target1Pts, setTarget1Pts] = useState(DEFAULT_TARGET1_PTS);
  const [firstEntryTp1Pts, setFirstEntryTp1Pts] = useState(DEFAULT_FIRST_ENTRY_TP1_PTS);
  const [target2Pts, setTarget2Pts] = useState(DEFAULT_TARGET2_PTS);
  const [lotsPerEntry, setLotsPerEntry] = useState(DEFAULT_LOTS_PER_ENTRY);
  const [strikeOffset, setStrikeOffset] = useState(DEFAULT_STRIKE_OFFSET);
  const [initialLots, setInitialLots] = useState(DEFAULT_INITIAL_LOTS);
  const [addLots, setAddLots] = useState(DEFAULT_ADD_LOTS);
  const [entryLots, setEntryLots] = useState<number[]>(DEFAULT_ENTRY_LOTS);
  const [stopDistance, setStopDistance] = useState(DEFAULT_STOP_DISTANCE);
  const [tp2TrailPoints, setTp2TrailPoints] = useState(DEFAULT_TP2_TRAIL);
  const [reEntryEnabled, setReEntryEnabled] = useState(true);
  const [maxReEntries, setMaxReEntries] = useState(DEFAULT_MAX_RE_ENTRIES);
  const [callEnabled, setCallEnabled] = useState(true);
  const [putEnabled, setPutEnabled] = useState(true);
  const [reEntryGap, setReEntryGap] = useState(DEFAULT_RE_ENTRY_GAP);
  const [tradeDirection, setTradeDirection] = useState<"BOTH" | "CALL_ONLY" | "PUT_ONLY">("BOTH");
  const [autoSquareOffTime, setAutoSquareOffTime] = useState("15:30");
  const [ceStopLoss, setCeStopLoss] = useState<number | null>(null);
  const [peStopLoss, setPeStopLoss] = useState<number | null>(null);
  const [ceT1, setCeT1] = useState<number[]>([]);
  const [ceT2, setCeT2] = useState<number[]>([]);
  const [peT1, setPeT1] = useState<number[]>([]);
  const [peT2, setPeT2] = useState<number[]>([]);
  const [tradingLogs, setTradingLogs] = useState<ApiLogRow[]>([]);
  const [activeTrades, setActiveTrades] = useState<ApiActiveRow[]>([]);
  const [completedTrades, setCompletedTrades] = useState<ApiCompletedRow[]>([]);
  const [persistError, setPersistError] = useState<string | null>(null);
  const [bootDone, setBootDone] = useState(false);
  const [clearingCompleted, setClearingCompleted] = useState(false);
  const [clearingLogs, setClearingLogs] = useState(false);
  const [engineAdaptiveHigh, setEngineAdaptiveHigh] = useState<number | null>(null);
  const [engineAdaptiveLow, setEngineAdaptiveLow] = useState<number | null>(null);
  const [serverOnline, setServerOnline] = useState(true);
  const wasServerOnlineRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = getStoredToken();
      if (!token) {
        if (!cancelled) setBootDone(true);
        return;
      }
      try {
        const res = await fetch(`${getApiBase()}/trading/settings`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: 'no-store',
          signal: AbortSignal.timeout(12_000),
        });
        const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok || cancelled) return;
        const cfg = (data.config as Record<string, unknown>) || {};
        if (typeof cfg.startTime === 'string') setStartTime(cfg.startTime.slice(0, 5));
        if (typeof cfg.endTime === 'string') setEndTime(cfg.endTime.slice(0, 5));
        const rc = num(cfg.referenceClose);
        if (rc != null && rc > 0) setReferenceClose(rc);
        const pp = num(cfg.partialClosePercent);
        if (pp != null && pp > 0) setPartialClosePercent(Math.min(100, Math.round(pp)));
        const t1Lots = num(cfg.tp1ExitLots);
        const t2Lots = num(cfg.tp2ExitLots);
        const lpeBoot = num(cfg.lotsPerEntry) ?? DEFAULT_LOTS_PER_ENTRY;
        const tcBoot = num(cfg.tradeCount) ?? DEFAULT_NUM_ENTRIES;
        const totalBoot = Math.max(1, lpeBoot * tcBoot);
        if (t1Lots != null && t1Lots > 0) {
          setTp1ExitLots(Math.round(t1Lots));
          const t2 = t2Lots != null && t2Lots > 0 ? Math.round(t2Lots) : totalBoot - Math.round(t1Lots);
          setTp2ExitLots(Math.max(1, t2));
        } else if (pp != null && pp > 0) {
          const t1 = Math.max(1, Math.round((totalBoot * pp) / 100));
          setTp1ExitLots(t1);
          setTp2ExitLots(Math.max(1, totalBoot - t1));
        }
        if (typeof cfg.firstEntryEnabled === 'boolean') setFirstEntryEnabled(cfg.firstEntryEnabled);
        const acrh = num(cfg.adaptiveCallRetraceHigh);
        if (acrh != null && acrh > 0 && acrh < 500) setAdaptiveCallRetraceHigh(Math.round(acrh));
        const aprh = num(cfg.adaptivePutRetraceHigh);
        if (aprh != null && aprh > 0 && aprh < 500) setAdaptivePutRetraceHigh(Math.round(aprh));
        const aprl = num(cfg.adaptivePutRetraceLow);
        if (aprl != null && aprl > 0 && aprl < 500) setAdaptivePutRetraceLow(Math.round(aprl));
        const acrl = num(cfg.adaptiveCallRetraceLow);
        if (acrl != null && acrl > 0 && acrl < 500) setAdaptiveCallRetraceLow(Math.round(acrl));
        if (cfg.slMode === 'manual' || cfg.slMode === 'auto') setSlMode(cfg.slMode);
        const elsz = cfg.exchangeLotSize;
        if (typeof elsz === 'number' && elsz > 0) setExchangeLotSize(elsz);
        const g = num(cfg.entryTrigger) ?? num(cfg.gap);
        if (g != null && g > 0) setEntryGap(Math.round(g));
        const off = num(cfg.averagingGap) ?? num(cfg.offset);
        if (off != null && off > 0) setAddGap(Math.round(off));
        const tc = num(cfg.maxEntries) ?? num(cfg.tradeCount);
        if (tc != null && tc > 0) setNumEntries(Math.min(20, Math.max(1, Math.round(tc))));
        const t1 = num(cfg.target1Points);
        if (t1 != null && t1 > 0) setTarget1Pts(Math.round(t1));
        const t1i = num(cfg.firstEntryTp1Points);
        if (t1i != null && t1i > 0) setFirstEntryTp1Pts(Math.round(t1i));
        const trail = num(cfg.tp2TrailPoints);
        if (trail != null && trail > 0) setTp2TrailPoints(Math.round(trail));
        const t2 = num(cfg.target2Points);
        if (t2 != null && t2 > 0) setTarget2Pts(Math.round(t2));
        const il = num(cfg.initialLots) ?? num(cfg.lotsPerEntry);
        const addLotsCfg = num(cfg.addLots);
        const entriesN = num(cfg.maxEntries) ?? num(cfg.tradeCount) ?? DEFAULT_NUM_ENTRIES;
        if (il != null && il > 0) {
          setInitialLots(Math.min(100, Math.max(1, Math.round(il))));
          setLotsPerEntry(Math.min(100, Math.max(1, Math.round(il))));
        }
        if (addLotsCfg != null && addLotsCfg > 0) setAddLots(Math.round(addLotsCfg));
        const ilResolved = il != null && il > 0 ? Math.round(il) : DEFAULT_INITIAL_LOTS;
        const alResolved = addLotsCfg != null && addLotsCfg > 0 ? Math.round(addLotsCfg) : DEFAULT_ADD_LOTS;
        if (Array.isArray(cfg.entryLots) && cfg.entryLots.length) {
          const parsed = cfg.entryLots.map((x) => Math.max(1, Math.round(Number(x))));
          setEntryLots(normalizeEntryLots(parsed, entriesN, ilResolved, alResolved));
        } else {
          setEntryLots(defaultEntryLots(entriesN, ilResolved, alResolved));
        }
        const so = num(cfg.strikeOffset);
        if (so != null && so >= 50) setStrikeOffset(Math.round(so));
        const sd = num(cfg.stopDistance);
        if (sd != null && sd > 0) setStopDistance(Math.round(sd));
        if (typeof cfg.reEntryEnabled === 'boolean') setReEntryEnabled(cfg.reEntryEnabled);
        if (typeof cfg.callEnabled === 'boolean') setCallEnabled(cfg.callEnabled);
        if (typeof cfg.putEnabled === 'boolean') setPutEnabled(cfg.putEnabled);
        const mre = num(cfg.maxReEntries);
        if (mre != null && mre >= 0) setMaxReEntries(Math.round(mre));
        const reg = num(cfg.reEntryGap);
        if (reg != null && reg > 0) setReEntryGap(Math.round(reg));
        const td = String(cfg.tradeDirection || "BOTH").toUpperCase();
        if (td === "CALL_ONLY" || td === "PUT_ONLY" || td === "BOTH") setTradeDirection(td);
        if (typeof cfg.autoSquareOffTime === "string") setAutoSquareOffTime(cfg.autoSquareOffTime.slice(0, 5));

        const nBoot = clampNumEntries(num(cfg.tradeCount) ?? DEFAULT_NUM_ENTRIES);
        const ceSl = num(cfg.sensexCeStopLoss);
        const peSl = num(cfg.sensexPeStopLoss);
        if (ceSl != null && ceSl > 0) setCeStopLoss(ceSl);
        else if (rc != null && rc > 0) setCeStopLoss(rc);
        else setCeStopLoss(null);
        if (peSl != null && peSl > 0) setPeStopLoss(peSl);
        else if (rc != null && rc > 0) setPeStopLoss(rc);
        else setPeStopLoss(null);

        const c1 = parseNumArray(cfg.sensexCeT1);
        const c2 = parseNumArray(cfg.sensexCeT2);
        const p1 = parseNumArray(cfg.sensexPeT1);
        const p2 = parseNumArray(cfg.sensexPeT2);
        const gBoot = num(cfg.gap) ?? DEFAULT_ENTRY_GAP;
        const offBoot = num(cfg.offset) ?? DEFAULT_ADD_GAP;
        const t1b = num(cfg.target1Points) ?? DEFAULT_TARGET1_PTS;
        const t2b = num(cfg.target2Points) ?? DEFAULT_TARGET2_PTS;
        const baseBoot = rc != null && rc > 0 ? rc : null;
        if (
          baseBoot != null &&
          c1 &&
          c2 &&
          p1 &&
          p2 &&
          c1.length === nBoot &&
          c2.length === nBoot &&
          p1.length === nBoot &&
          p2.length === nBoot
        ) {
          setCeT1(c1.map(roundPx));
          setCeT2(c2.map(roundPx));
          setPeT1(p1.map(roundPx));
          setPeT2(p2.map(roundPx));
        } else if (baseBoot != null) {
          const d0 = defaultTargetArrays(baseBoot, gBoot, offBoot, nBoot, t1b, t2b);
          setCeT1(d0.ceT1);
          setCeT2(d0.ceT2);
          setPeT1(d0.peT1);
          setPeT2(d0.peT2);
        }

        setLegEntryMode(normalizeLegEntryMode(cfg.legEntryMode), { persist: false });

        const ah = num(cfg.adaptiveHigh);
        if (ah != null && ah > 0) setEngineAdaptiveHigh(ah);
        const al = num(cfg.adaptiveLow);
        if (al != null && al > 0) setEngineAdaptiveLow(al);

        const tm = typeof data.trading_mode === 'string' ? data.trading_mode.toUpperCase() : 'PAPER';
        setTradingMode(tm === 'LIVE' ? 'LIVE' : 'PAPER');
        setAlgoEnabled(Boolean(data.algo_running));
      } finally {
        if (!cancelled) setBootDone(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setAlgoEnabled, setLegEntryMode]);

  useEffect(() => {
    let cancelled = false;
    const base = getApiBase();

    async function pingHealth() {
      try {
        const res = await fetch(`${base}/health`, { cache: 'no-store' });
        const data = (await res.json().catch(() => ({}))) as { status?: string };
        const online = res.ok && data.status === 'ok';
        if (!cancelled) {
          setServerOnline(online);
          if (!online) {
            setActiveTrades([]);
            setCompletedTrades([]);
            setTradingLogs([]);
          }
        }
      } catch {
        if (!cancelled) {
          setServerOnline(false);
          setActiveTrades([]);
          setCompletedTrades([]);
          setTradingLogs([]);
        }
      }
    }

    void pingHealth();
    const id = window.setInterval(() => void pingHealth(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!bootDone) return;
    const prev = wasServerOnlineRef.current;
    if (serverOnline && !prev) {
      const token = getStoredToken();
      if (token) {
        void fetch(`${getApiBase()}/trading/reconcile`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {});
      }
    }
    wasServerOnlineRef.current = serverOnline;
  }, [bootDone, serverOnline]);

  useEffect(() => {
    if (!bootDone || !serverOnline || isBacktestPage) return;
    const token = getStoredToken();
    if (!token) return;
    const headers = { Authorization: `Bearer ${token}` };

    const pollActive = async () => {
      try {
        const res = await fetch(`${getApiBase()}/trading/positions/active`, { headers, cache: 'no-store' });
        if (res.ok) setIfChanged(setActiveTrades, activeSigRef, (await res.json()) as ApiActiveRow[]);
      } catch {
        /* ignore */
      }
    };

    const pollSecondary = async () => {
      try {
        const [r1, r3, r4] = await Promise.all([
          fetch(`${getApiBase()}/trading/logs?limit=80`, { headers, cache: 'no-store' }),
          fetch(`${getApiBase()}/trading/positions/completed?limit=150`, { headers, cache: 'no-store' }),
          fetch(`${getApiBase()}/trading/settings`, { headers, cache: 'no-store' }),
        ]);
        if (r1.ok) setIfChanged(setTradingLogs, logsSigRef, (await r1.json()) as ApiLogRow[]);
        if (r3.ok) {
          const rows = (await r3.json()) as ApiCompletedRow[];
          if (completedClearPendingRef.current) {
            if (rows.length === 0) completedClearPendingRef.current = false;
          } else {
            setIfChanged(setCompletedTrades, completedSigRef, rows);
          }
        }
        if (r4.ok) {
          const data = (await r4.json()) as Record<string, unknown>;
          const cfg = (data.config as Record<string, unknown>) || {};
          const ah = num(cfg.adaptiveHigh);
          setEngineAdaptiveHigh(ah != null && ah > 0 ? ah : null);
          const al = num(cfg.adaptiveLow);
          setEngineAdaptiveLow(al != null && al > 0 ? al : null);
        }
      } catch {
        /* ignore */
      }
    };

    void pollActive();
    void pollSecondary();
    const activeId = window.setInterval(() => void pollActive(), 1000);
    const secondaryId = window.setInterval(() => void pollSecondary(), 5000);
    return () => {
      window.clearInterval(activeId);
      window.clearInterval(secondaryId);
    };
  }, [bootDone, serverOnline, isBacktestPage]);

  const fetchStartBarClose = useCallback(async () => {
    const token = getStoredToken();
    if (!token) return;
    const st = startTime.length >= 5 ? startTime.slice(0, 5) : startTime;
    setStartBarLoading(true);
    setStartBarErr(null);
    try {
      const qs = new URLSearchParams({ start: st });
      const res = await fetch(`${getApiBase()}/angel/start-bar-close?${qs}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const detail = httpErrorDetail(data, `HTTP ${res.status}`);
        setStartBarErr(detail);
        setStartBar(null);
        return;
      }
      const nextStartBar = {
        ok: Boolean(data.ok),
        start_time: typeof data.start_time === 'string' ? data.start_time : st,
        close: typeof data.close === 'number' ? data.close : null,
        candle_time: typeof data.candle_time === 'string' ? data.candle_time : null,
        date: typeof data.date === 'string' ? data.date : null,
        is_fallback: Boolean(data.is_fallback),
        message: typeof data.message === 'string' ? data.message : '',
      };
      setIfChanged(setStartBar, startBarSigRef, nextStartBar);
      if (typeof data.message === 'string' && data.message && !data.ok) {
        setStartBarErr(data.message);
      }
    } catch {
      setStartBarErr('Cannot load start-bar close');
      setStartBar(null);
    } finally {
      setStartBarLoading(false);
    }
  }, [startTime]);

  useEffect(() => {
    const first = window.setTimeout(() => void fetchStartBarClose(), 0);
    const id = window.setInterval(() => void fetchStartBarClose(), 60_000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [fetchStartBarClose]);

  const runAngelServerRefresh = useCallback(async () => {
    setAngelRefreshBusy(true);
    setAngelRefreshFeedback(null);
    try {
      const result = await refreshAngelSession();
      if (result.ok) {
        setAngelRefreshFeedback(result.message ?? 'Angel session refreshed. Reloading…');
        window.location.reload();
        return;
      }
      setAngelRefreshFeedback(result.error ?? 'Token refresh failed.');
    } catch {
      setAngelRefreshFeedback('Network error while refreshing Angel session.');
    } finally {
      setAngelRefreshBusy(false);
    }
  }, []);

  const showAngelServerRefresh =
    angelTokenExpired ||
    isAngelTokenErrorText(
      [angelErr, angel?.angel_message, startBarErr, startBar?.message].filter(Boolean).join('\n')
    );

  /** Calculated legs use **start bar close only** — never live LTP. Refresh until close is available. */
  const startBarCloseAnchor =
    startBar?.close != null && Number.isFinite(startBar.close) && startBar.close > 0
      ? startBar.close
      : null;

  const displayReferencePrice =
    startBar?.is_fallback && startBarCloseAnchor != null
      ? startBarCloseAnchor
      : referencePrice > 0
        ? referencePrice
        : null;

  const displayReferenceSource =
    startBar?.is_fallback && startBarCloseAnchor != null
      ? 'last-session'
      : referencePrice > 0
        ? 'live'
        : null;

  useEffect(() => {
    if (startBarCloseAnchor == null || !Number.isFinite(startBarCloseAnchor)) return;
    const prev = lastStartBarCloseRef.current;
    if (prev === startBarCloseAnchor) return;

    setReferenceClose(startBarCloseAnchor);
    lastStartBarCloseRef.current = startBarCloseAnchor;

    if (prev === null) {
      setCeStopLoss((x) => (x == null ? startBarCloseAnchor : x));
      setPeStopLoss((x) => (x == null ? startBarCloseAnchor : x));
      const d = defaultTargetArrays(
        startBarCloseAnchor,
        entryGap,
        addGap,
        numEntries,
        target1Pts,
        target2Pts
      );
      setCeT1((c) => (c.length === 0 ? d.ceT1 : c));
      setCeT2((c) => (c.length === 0 ? d.ceT2 : c));
      setPeT1((c) => (c.length === 0 ? d.peT1 : c));
      setPeT2((c) => (c.length === 0 ? d.peT2 : c));
      return;
    }

    setCeStopLoss(startBarCloseAnchor);
    setPeStopLoss(startBarCloseAnchor);
    const d = defaultTargetArrays(
      startBarCloseAnchor,
      entryGap,
      addGap,
      numEntries,
      target1Pts,
      target2Pts
    );
    setCeT1(d.ceT1);
    setCeT2(d.ceT2);
    setPeT1(d.peT1);
    setPeT2(d.peT2);
  }, [startBarCloseAnchor, entryGap, addGap, numEntries, target1Pts, target2Pts]);

  const resetTargetsFromStructure = useCallback(
    (next: {
      entryGap?: number;
      addGap?: number;
      numEntries?: number;
      target1Pts?: number;
      target2Pts?: number;
    }) => {
      const eg = next.entryGap ?? entryGap;
      const ag = next.addGap ?? addGap;
      const ne = next.numEntries ?? numEntries;
      const t1p = next.target1Pts ?? target1Pts;
      const t2p = next.target2Pts ?? target2Pts;
      const b = referenceClose ?? startBarCloseAnchor;
      if (b == null || !Number.isFinite(b)) return;
      const d = defaultTargetArrays(b, eg, ag, ne, t1p, t2p);
      setCeT1(d.ceT1);
      setCeT2(d.ceT2);
      setPeT1(d.peT1);
      setPeT2(d.peT2);
    },
    [referenceClose, startBarCloseAnchor, entryGap, addGap, numEntries, target1Pts, target2Pts]
  );

  const previewRows = useMemo(() => {
    const base = referenceClose ?? startBarCloseAnchor;
    if (base == null || !Number.isFinite(base)) return null;
    const n = clampNumEntries(numEntries);
    if (ceT1.length !== n || ceT2.length !== n || peT1.length !== n || peT2.length !== n) return null;
    return buildPreviewLegRows(
      base,
      entryGap,
      addGap,
      numEntries,
      lotsPerEntry,
      displayReferencePrice,
      ceT1,
      ceT2,
      peT1,
      peT2
    );
  }, [
    referenceClose,
    startBarCloseAnchor,
    entryGap,
    addGap,
    numEntries,
    lotsPerEntry,
    displayReferencePrice,
    ceT1,
    ceT2,
    peT1,
    peT2,
  ]);

  const effectiveBase = referenceClose ?? startBarCloseAnchor;

  const applyExitLots = useCallback(
    (tp1: number, tp2: number) => {
      const synced = syncExitLotsToEngine(
        tp1,
        tp2,
        setLotsPerEntry,
        setNumEntries,
        setPartialClosePercent,
      );
      setTp1ExitLots(synced.tp1);
      setTp2ExitLots(synced.tp2);
    },
    [],
  );

  const buildDashboardConfig = useCallback((): Record<string, unknown> => {
    const out: Record<string, unknown> = {
      startTime,
      endTime,
      gap: entryGap,
      entryTrigger: entryGap,
      offset: addGap,
      averagingGap: addGap,
      tradeCount: numEntries,
      maxEntries: numEntries,
      target1Points: target1Pts,
      firstEntryTp1Points: firstEntryTp1Pts,
      target2Points: target2Pts,
      tp2TrailPoints,
      strikeOffset,
      initialLots,
      addLots,
      entryLots: normalizeEntryLots(entryLots, numEntries, initialLots, addLots),
      stopDistance,
      lotsPerEntry: Math.max(1, Math.min(100, Math.round(initialLots))),
      sensexCeT1: ceT1,
      sensexCeT2: ceT2,
      sensexPeT1: peT1,
      sensexPeT2: peT2,
      tp1ExitLots,
      tp2ExitLots,
      firstEntryEnabled,
      reEntryEnabled,
      maxReEntries,
      reEntryGap,
      tradeDirection,
      autoSquareOffTime,
      callEnabled,
      putEnabled,
      adaptiveCallRetraceHigh,
      adaptivePutRetraceHigh,
      adaptivePutRetraceLow,
      adaptiveCallRetraceLow,
      putSL: '',
      callSL: '',
      slMode,
      exchangeLotSize,
      legEntryMode,
      trades: [],
    };
    if (referenceClose != null && Number.isFinite(referenceClose) && referenceClose > 0) {
      out.referenceClose = referenceClose;
    }
    const baseForSl = referenceClose ?? startBarCloseAnchor;
    if (baseForSl != null && Number.isFinite(baseForSl) && baseForSl > 0) {
      out.sensexCeStopLoss = ceStopLoss ?? baseForSl;
      out.sensexPeStopLoss = peStopLoss ?? baseForSl;
    }
    return out;
  }, [
    referenceClose,
    startTime,
    endTime,
    entryGap,
    addGap,
    numEntries,
    target1Pts,
    target2Pts,
    firstEntryTp1Pts,
    lotsPerEntry,
    ceT1,
    ceT2,
    peT1,
    peT2,
    ceStopLoss,
    peStopLoss,
    partialClosePercent,
    tp1ExitLots,
    tp2ExitLots,
    firstEntryEnabled,
    adaptiveCallRetraceHigh,
    adaptivePutRetraceHigh,
    adaptivePutRetraceLow,
    adaptiveCallRetraceLow,
    slMode,
    exchangeLotSize,
    legEntryMode,
    strikeOffset,
    initialLots,
    addLots,
    entryLots,
    stopDistance,
    tp2TrailPoints,
    reEntryEnabled,
    maxReEntries,
    reEntryGap,
    tradeDirection,
    autoSquareOffTime,
    callEnabled,
    putEnabled,
    startBarCloseAnchor,
  ]);

  const pushSettingsToServer = useCallback(
    async (overrides?: Partial<{ algo_running: boolean; trading_mode: TradingMode }>) => {
      const token = getStoredToken();
      if (!token) return;
      const mode = overrides?.trading_mode ?? tradingMode;
      const run = overrides?.algo_running ?? algoEnabled;
      const body = {
        config: buildDashboardConfig(),
        trading_mode: mode,
        algo_running: run,
      };
      try {
        const res = await fetch(`${getApiBase()}/trading/settings`, {
          method: 'PUT',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(body),
        });
        const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok) {
          setPersistError(httpErrorDetail(data, `HTTP ${res.status}`));
          return;
        }
        setPersistError(null);
        if (typeof data.trading_mode === 'string') {
          const u = data.trading_mode.toUpperCase();
          setTradingMode(u === 'LIVE' ? 'LIVE' : 'PAPER');
        }
        if (typeof data.algo_running === 'boolean') setAlgoEnabled(data.algo_running);
      } catch {
        setPersistError('Cannot save trading settings');
      }
    },
    [algoEnabled, tradingMode, buildDashboardConfig, setAlgoEnabled]
  );

  useEffect(() => {
    if (!bootDone) return;
    if (persistTimerRef.current) window.clearTimeout(persistTimerRef.current);
    persistTimerRef.current = window.setTimeout(() => {
      persistTimerRef.current = null;
      void pushSettingsToServer();
    }, 500);
    return () => {
      if (persistTimerRef.current) window.clearTimeout(persistTimerRef.current);
    };
  }, [
    bootDone,
    pushSettingsToServer,
    referenceClose,
    startTime,
    endTime,
    partialClosePercent,
    tp1ExitLots,
    tp2ExitLots,
    firstEntryEnabled,
    adaptiveCallRetraceHigh,
    adaptivePutRetraceHigh,
    adaptivePutRetraceLow,
    adaptiveCallRetraceLow,
    slMode,
    tradingMode,
    algoEnabled,
    exchangeLotSize,
    legEntryMode,
    entryGap,
    addGap,
    numEntries,
    target1Pts,
    target2Pts,
    firstEntryTp1Pts,
    lotsPerEntry,
    ceT1,
    ceT2,
    peT1,
    peT2,
    ceStopLoss,
    peStopLoss,
    strikeOffset,
    initialLots,
    addLots,
    entryLots,
    stopDistance,
    tp2TrailPoints,
    reEntryEnabled,
    maxReEntries,
    reEntryGap,
    tradeDirection,
    autoSquareOffTime,
    callEnabled,
    putEnabled,
  ]);

  const closeLegManual = useCallback(
    async (legLabel: string) => {
      const token = getStoredToken();
      if (!token) return;
      try {
        const res = await fetch(`${getApiBase()}/trading/legs/${encodeURIComponent(legLabel)}/close`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
          setPersistError(httpErrorDetail(data, `HTTP ${res.status}`));
          return;
        }
        setPersistError(null);
      } catch {
        setPersistError('Manual close request failed');
      }
    },
    []
  );

  const clearCompletedTrades = useCallback(async () => {
    const token = getStoredToken();
    if (!token) return;
    completedClearPendingRef.current = true;
    completedSigRef.current = '[]';
    setCompletedTrades([]);
    setPersistError(null);
    try {
      const res = await fetch(`${getApiBase()}/trading/positions/completed`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        setPersistError(httpErrorDetail(data, `HTTP ${res.status}`));
        completedClearPendingRef.current = false;
        return;
      }
      completedClearPendingRef.current = false;
    } catch {
      setPersistError('Could not clear completed trades');
      completedClearPendingRef.current = false;
    }
  }, []);

  const clearTradingLogs = useCallback(async () => {
    const token = getStoredToken();
    if (!token) return;
    setClearingLogs(true);
    try {
      const res = await fetch(`${getApiBase()}/trading/logs`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setPersistError(httpErrorDetail(data, `HTTP ${res.status}`));
        return;
      }
      setPersistError(null);
      setTradingLogs([]);
    } catch {
      setPersistError('Could not clear trading logs');
    } finally {
      setClearingLogs(false);
    }
  }, []);

  return {
    algoEnabled,
    setAlgoEnabled,
    legEntryMode,
    setLegEntryMode,
    tradingMode,
    setTradingMode,
    referencePrice,
    displayReferencePrice,
    displayReferenceSource,
    angel,
    angelErr,
    angelTokenExpired,
    fetchAngel,
    runAngelServerRefresh,
    showAngelServerRefresh,
    angelRefreshBusy,
    angelRefreshFeedback,
    startTime,
    setStartTime,
    endTime,
    setEndTime,
    startBar,
    startBarErr,
    startBarLoading,
    fetchStartBarClose,
    referenceClose,
    effectiveBase,
    startBarCloseAnchor,
    entryGap,
    setEntryGap,
    addGap,
    setAddGap,
    numEntries,
    setNumEntries,
    target1Pts,
    setTarget1Pts,
    firstEntryTp1Pts,
    setFirstEntryTp1Pts,
    target2Pts,
    setTarget2Pts,
    lotsPerEntry,
    setLotsPerEntry,
    strikeOffset,
    setStrikeOffset,
    initialLots,
    setInitialLots,
    addLots,
    setAddLots,
    entryLots,
    setEntryLots,
    stopDistance,
    setStopDistance,
    tp2TrailPoints,
    setTp2TrailPoints,
    reEntryEnabled,
    setReEntryEnabled,
    maxReEntries,
    setMaxReEntries,
    callEnabled,
    setCallEnabled,
    putEnabled,
    setPutEnabled,
    reEntryGap,
    setReEntryGap,
    tradeDirection,
    setTradeDirection,
    autoSquareOffTime,
    setAutoSquareOffTime,
    exchangeLotSize,
    setExchangeLotSize,
    partialClosePercent,
    setPartialClosePercent,
    tp1ExitLots,
    tp2ExitLots,
    applyExitLots,
    firstEntryEnabled,
    setFirstEntryEnabled,
    adaptiveCallRetraceHigh,
    setAdaptiveCallRetraceHigh,
    adaptivePutRetraceHigh,
    setAdaptivePutRetraceHigh,
    adaptivePutRetraceLow,
    setAdaptivePutRetraceLow,
    adaptiveCallRetraceLow,
    setAdaptiveCallRetraceLow,
    slMode,
    setSlMode,
    ceStopLoss,
    setCeStopLoss,
    peStopLoss,
    setPeStopLoss,
    ceT1,
    setCeT1,
    ceT2,
    setCeT2,
    peT1,
    setPeT1,
    peT2,
    setPeT2,
    previewRows,
    resetTargetsFromStructure,
    tradingLogs,
    activeTrades,
    completedTrades,
    persistError,
    bootDone,
    clearingCompleted,
    clearingLogs,
    pushSettingsToServer,
    closeLegManual,
    clearCompletedTrades,
    clearTradingLogs,
    buildDashboardConfig,
    engineAdaptiveHigh,
    engineAdaptiveLow,
    serverOnline,
    pickAngelQuoteRow,
    quotePriceFromRow,
    pctFromRow,
    netFromRow,
    fmtInr,
    formatLogTimestamp,
    formatTradeTimeIST,
    roundPx,
  };
}
