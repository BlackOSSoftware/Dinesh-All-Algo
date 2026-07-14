"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, Calendar, Compass, Layers, Repeat, Target, Zap } from "lucide-react";

import {
  AnalyticsPanel,
  BtHeader,
  BtToggle,
  btInput,
  DirectionRadio,
  EntryLotsSteppers,
  Field,
  NumStepper,
  RunSection,
  SettingCard,
  SummaryGrid,
} from "@/components/trader/backtest-premium-ui";
import {
  AdaptiveTimelineSection,
  BacktestGuideSection,
  BaseTriggerSection,
  NetPointBreakdown,
  PlannedLevelsSection,
  PriceChartSection,
  TradeRecordSection,
} from "@/components/trader/backtest-analysis-ui";
import { useTradingDashboard } from "@/components/trader/trading-dashboard-context";
import { cn } from "@/components/ui";
import { getApiBase, getStoredToken } from "@/lib/auth";
import {
  MAX_BACKTEST_DAYS,
  addDaysIso,
  dateRange,
  round,
  type Side,
  type Trade,
} from "@/lib/backtest-engine";
import {
  buildNetBreakdown,
  cycleTableRowsToExportRows,
  defaultEntryLots,
  exportExcelBlob,
  flattenLogToTableRows,
  normalizeEntryLots,
  fallbackDayDetails,
  mapDayDetails,
  mapDaySummary,
  type DayDetail,
  type DaySummaryRow,
} from "@/lib/backtest-trend-analysis";

type TradeDirection = "BOTH" | "CALL_ONLY" | "PUT_ONLY";

type BacktestParams = {
  startTime: string;
  endTime: string;
  entryTrigger: number;
  strikeOffset: number;
  stopDistance: number;
  initialLots: number;
  addLots: number;
  entryLots: number[];
  averagingGap: number;
  maxEntries: number;
  tp1Points: number;
  firstEntryTp1Points: number;
  tp2Trail: number;
  reEntryGap: number;
  autoSquareOffTime: string;
  tradeDirection: TradeDirection;
  callEnabled: boolean;
  putEnabled: boolean;
  reEntryEnabled: boolean;
  firstEntryEnabled: boolean;
  maxReEntries: number;
};

type BacktestStats = {
  total_pnl: number;
  net_profit: number;
  gross_profit: number;
  gross_loss: number;
  win_rate: number;
  loss_rate: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  profit_factor: number;
  max_drawdown: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  avg_win: number;
  avg_loss: number;
  expectancy: number;
  largest_profit: number;
  largest_loss: number;
  final_capital: number;
  return_pct: number;
  trade_cycles?: number;
  initial_cycles?: number;
  reentry_cycles?: number;
  exit_events?: number;
  closed_trades?: number;
  averaging_events?: number;
  max_averaging_per_cycle?: number;
  avg_entries_per_cycle?: number;
};

const BT_DEFAULTS: BacktestParams = {
  startTime: "09:15",
  endTime: "15:30",
  entryTrigger: 191,
  strikeOffset: 200,
  stopDistance: 191,
  initialLots: 2,
  addLots: 1,
  entryLots: [2, 1, 1, 1],
  averagingGap: 45,
  maxEntries: 4,
  tp1Points: 45,
  firstEntryTp1Points: 70,
  tp2Trail: 30,
  reEntryGap: 70,
  autoSquareOffTime: "15:30",
  tradeDirection: "BOTH",
  callEnabled: true,
  putEnabled: true,
  reEntryEnabled: true,
  firstEntryEnabled: true,
  maxReEntries: 3,
};

const PRESET_STORAGE_KEY = "sensex-backtest-presets";

type StoredPreset = {
  name: string;
  fromDate: string;
  toDate: string;
  params: BacktestParams;
};

const todayIso = () => new Date().toISOString().slice(0, 10);
const csvCell = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`;

function apiErrorMessage(data: unknown, fallback: string) {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  if (data && typeof data === "object" && "message" in data) {
    const message = (data as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}

function paramsToConfig(p: BacktestParams): Record<string, unknown> {
  return {
    startTime: p.startTime,
    endTime: p.endTime,
    gap: p.entryTrigger,
    entryTrigger: p.entryTrigger,
    strikeOffset: p.strikeOffset,
    stopDistance: p.stopDistance,
    initialLots: p.initialLots,
    addLots: p.addLots,
    entryLots: normalizeEntryLots(p.entryLots, p.maxEntries, p.initialLots, p.addLots),
    averagingGap: p.averagingGap,
    offset: p.averagingGap,
    maxEntries: p.maxEntries,
    tradeCount: p.maxEntries,
    target1Points: p.tp1Points,
    firstEntryTp1Points: p.firstEntryTp1Points,
    tp2TrailPoints: p.tp2Trail,
    reEntryGap: p.reEntryGap,
    autoSquareOffTime: p.autoSquareOffTime,
    tradeDirection: p.tradeDirection,
    callEnabled: p.callEnabled,
    putEnabled: p.putEnabled,
    reEntryEnabled: p.reEntryEnabled,
    firstEntryEnabled: p.firstEntryEnabled,
    maxReEntries: p.maxReEntries,
    lotsPerEntry: p.initialLots,
  };
}

function loadFromDashboard(d: ReturnType<typeof useTradingDashboard>): BacktestParams {
  return {
    startTime: d.startTime || BT_DEFAULTS.startTime,
    endTime: d.endTime || BT_DEFAULTS.endTime,
    entryTrigger: d.entryGap,
    strikeOffset: d.strikeOffset,
    stopDistance: d.stopDistance,
    initialLots: d.initialLots,
    addLots: d.addLots,
    entryLots: normalizeEntryLots(d.entryLots, d.numEntries, d.initialLots, d.addLots),
    averagingGap: d.addGap,
    maxEntries: d.numEntries,
    tp1Points: d.target1Pts,
    firstEntryTp1Points: d.firstEntryTp1Pts ?? 70,
    tp2Trail: d.tp2TrailPoints,
    reEntryGap: d.reEntryGap,
    autoSquareOffTime: d.autoSquareOffTime,
    tradeDirection: d.tradeDirection,
    callEnabled: d.callEnabled,
    putEnabled: d.putEnabled,
    reEntryEnabled: d.reEntryEnabled,
    firstEntryEnabled: d.firstEntryEnabled,
    maxReEntries: d.maxReEntries,
  };
}

function loadPresets(): StoredPreset[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(PRESET_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as StoredPreset[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function savePresets(list: StoredPreset[]) {
  localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(list));
}

type DayRow = DaySummaryRow;

export function BacktestView() {
  const d = useTradingDashboard();
  const today = todayIso();
  const [fromDate, setFromDate] = useState(addDaysIso(today, -6));
  const [toDate, setToDate] = useState(today);
  const [bt, setBt] = useState<BacktestParams>(BT_DEFAULTS);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [daySummaries, setDaySummaries] = useState<DayRow[]>([]);
  const [dayDetails, setDayDetails] = useState<DayDetail[]>([]);
  const [chartDate, setChartDate] = useState("");
  const [stats, setStats] = useState<BacktestStats | null>(null);
  const [tradeLog, setTradeLog] = useState<Record<string, unknown>[]>([]);
  const [equityCurve, setEquityCurve] = useState<{ date: string; equity: number; daily_pnl: number }[]>([]);
  const [drawdownCurve, setDrawdownCurve] = useState<{ date: string; drawdown: number }[]>([]);
  const [daysRun, setDaysRun] = useState(0);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);
  const [presets, setPresets] = useState<string[]>([]);
  const [loadProgress, setLoadProgress] = useState({ pct: 0, day: 0, total: 0, elapsed: 0 });
  const loadStartRef = useRef(0);
  const progressTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const patch = useCallback((partial: Partial<BacktestParams>) => {
    setBt((prev) => ({ ...prev, ...partial }));
  }, []);

  const setDirection = useCallback((dir: TradeDirection) => {
    patch({
      tradeDirection: dir,
      callEnabled: dir !== "PUT_ONLY",
      putEnabled: dir !== "CALL_ONLY",
    });
  }, [patch]);

  const dayCount = useMemo(() => dateRange(fromDate, toDate).length, [fromDate, toDate]);
  const tradeTableRows = useMemo(() => flattenLogToTableRows(tradeLog), [tradeLog]);
  const netBreakdown = useMemo(() => buildNetBreakdown(daySummaries, trades), [daySummaries, trades]);

  const chartDay = useMemo(() => {
    const d = dayDetails.find((x) => x.date === chartDate) ?? dayDetails[0];
    return d ?? null;
  }, [dayDetails, chartDate]);

  const analysis = useMemo(() => {
    const monthly = new Map<string, number>();
    for (const row of daySummaries) {
      const m = row.date.slice(0, 7);
      monthly.set(m, (monthly.get(m) ?? 0) + row.points);
    }
    return {
      monthly: [...monthly.entries()].map(([month, points]) => ({ month, points })),
    };
  }, [daySummaries]);

  useEffect(() => {
    setPresets(loadPresets().map((p) => p.name));
  }, []);

  useEffect(() => {
    if (!loading) {
      if (progressTimerRef.current) clearInterval(progressTimerRef.current);
      return;
    }
    loadStartRef.current = Date.now();
    setLoadProgress({ pct: 5, day: 0, total: dayCount, elapsed: 0 });
    progressTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - loadStartRef.current) / 1000);
      setLoadProgress((p) => {
        const pct = Math.min(92, p.pct + Math.max(1, Math.floor(80 / Math.max(dayCount, 1))));
        const day = Math.min(p.total, Math.floor((pct / 100) * p.total));
        return { ...p, pct, day, elapsed };
      });
    }, 350);
    return () => {
      if (progressTimerRef.current) clearInterval(progressTimerRef.current);
    };
  }, [loading, dayCount]);

  async function loadAndRun() {
    const token = getStoredToken();
    if (!token) return;
    if (fromDate > toDate) {
      setMessage("From date must be on or before To date.");
      return;
    }
    if (dateRange(fromDate, toDate).length > MAX_BACKTEST_DAYS) {
      setMessage(`Maximum ${MAX_BACKTEST_DAYS} days per backtest.`);
      return;
    }

    setLoading(true);
    setMessage(null);
    setTrades([]);
    setDaySummaries([]);
    setDayDetails([]);
    setChartDate("");
    setStats(null);
    setTradeLog([]);
    setEquityCurve([]);
    setDrawdownCurve([]);
    setDaysRun(0);
    setHasRun(false);

    const t0 = performance.now();

    try {
      const res = await fetch(`${getApiBase()}/trading/backtest`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ from_date: fromDate, to_date: toDate, config: paramsToConfig(bt), interval: "1" }),
        cache: "no-store",
      });
      const data = (await res.json().catch(() => ({}))) as {
        detail?: unknown;
        stats?: BacktestStats;
        trades?: Array<Record<string, unknown>>;
        log?: Array<Record<string, unknown>>;
        cycle_records?: Array<Record<string, unknown>>;
        daily_summary?: Array<{
          date: string;
          base: number | null;
          call_trigger?: number | null;
          put_trigger?: number | null;
          points: number;
          trades: number;
        }>;
        day_details?: Array<Record<string, unknown>>;
        equity_curve?: { date: string; equity: number; daily_pnl: number }[];
        drawdown_curve?: { date: string; drawdown: number }[];
        days_count?: number;
      };
      if (!res.ok) throw new Error(apiErrorMessage(data, `HTTP ${res.status}`));

      const mapped: Trade[] = (data.trades ?? []).map((t, i) => ({
        id: Number(t.id) || i + 1,
        tradeDate: String(t.date ?? ""),
        side: (String(t.side ?? "CALL").toUpperCase() === "PUT" ? "PUT" : "CALL") as Side,
        entryTime: String(t.time ?? ""),
        exitTime: String(t.time ?? ""),
        entry: Number(t.entry ?? t.index_price ?? 0),
        exit: Number(t.exit_price ?? t.index_price ?? 0),
        entryLots: Number(t.lots ?? 1),
        exitLots: Number(t.lots ?? 1),
        points: Number(t.trade_pnl ?? 0),
        reason: (String(t.reason ?? t.exit_reason ?? "TP2").includes("SL")
          ? "SL"
          : String(t.reason ?? t.exit_reason ?? "").includes("SESSION")
            ? "SESSION_END"
            : String(t.reason ?? t.exit_reason ?? "").includes("TP1")
              ? "TP1"
              : "TP2") as Trade["reason"],
        entryType: String(t.entry_type ?? "INITIAL") as Trade["entryType"],
        note: String(t.exit_reason ?? ""),
      }));

      setTrades(mapped);
      const summaries = mapDaySummary(data.daily_summary ?? [], bt.entryTrigger);
      setDaySummaries(summaries);
      let details = mapDayDetails(data.day_details ?? [], bt.entryTrigger);
      if (!details.length && summaries.length) {
        details = fallbackDayDetails(summaries, data.log ?? [], {
          entryTrigger: bt.entryTrigger,
          stopDistance: bt.stopDistance,
          initialLots: bt.initialLots,
          addLots: bt.addLots,
          entryLots: bt.entryLots,
          averagingGap: bt.averagingGap,
          maxEntries: bt.maxEntries,
          tp1Points: bt.tp1Points,
          firstEntryTp1Points: bt.firstEntryTp1Points,
          tp2Trail: bt.tp2Trail,
          reEntryGap: bt.reEntryGap,
          reEntryEnabled: bt.reEntryEnabled,
        });
      }
      setDayDetails(details);
      setChartDate(details[0]?.date ?? summaries[0]?.date ?? "");
      setStats(data.stats ?? null);
      setTradeLog(data.log ?? []);
      setEquityCurve(data.equity_curve ?? []);
      setDrawdownCurve(data.drawdown_curve ?? []);
      setDaysRun(data.days_count ?? 0);
      setHasRun(true);
      setLoadProgress((p) => ({ ...p, pct: 100, day: p.total }));

      const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
      setMessage(
        `Completed · ${data.days_count ?? 0} day(s) · ${mapped.length} exits · ${data.stats?.total_pnl ?? 0} pts · ${elapsed}s`,
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Backtest failed.");
    } finally {
      setLoading(false);
    }
  }

  function exportCsv() {
    const cycleHeaders = [
      "#", "Date", "Time", "Cycle", "Action", "Side", "Kind", "Base", "Trigger", "Strike", "Strike Type",
      "Lots", "Total Lots", "TP1", "Adaptive H/L", "SL", "Exit", "Exit Reason", "Cycle P&L", "Running",
    ];
    const rows: unknown[][] = [
      ["BACKTEST REPORT"],
      ["From", fromDate],
      ["To", toDate],
      ["Days", daysRun],
      [],
      ["PERFORMANCE"],
      ...(stats ? Object.entries(stats).map(([k, v]) => [k.replaceAll("_", " "), v]) : []),
      [],
      ["DAILY P&L"],
      ["Date", "Base", "Call Trigger", "Put Trigger", "Trades", "Points"],
      ...daySummaries.map((r) => [r.date, r.base, r.callTrigger, r.putTrigger, r.trades, r.points]),
      [],
      ["TRADE RECORD"],
      cycleHeaders,
      ...cycleTableRowsToExportRows(tradeTableRows),
      [],
      ["CLOSED TRADES"],
      ["#", "Date", "Side", "Type", "Entry", "Exit", "Lots", "Reason", "Points"],
      ...trades.map((t) => [t.id, t.tradeDate, t.side, t.entryType, t.entry, t.exit, t.exitLots, t.reason, t.points]),
    ];
    const csv = rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `backtest-report-${fromDate}_${toDate}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportExcel() {
    const blob = exportExcelBlob([
      {
        title: "BASE & TRIGGER",
        headers: ["Date", "Base", "Call Trigger", "Put Trigger", "Trades", "Net Points"],
        rows: daySummaries.map((r) => [r.date, r.base, r.callTrigger, r.putTrigger, r.trades, r.points]),
      },
      {
        title: "TRADE RECORD",
        headers: [
          "#", "Date", "Time", "Cycle", "Action", "Side", "Kind", "Base", "Trigger", "Strike", "Strike Type",
          "Lots", "Total Lots", "TP1", "Adaptive H/L", "SL", "Exit", "Exit Reason", "Cycle P&L", "Running",
        ],
        rows: cycleTableRowsToExportRows(tradeTableRows),
      },
      {
        title: "NET BREAKDOWN BY DAY",
        headers: ["Date", "Points"],
        rows: netBreakdown.byDay.map((d) => [d.date, d.points]),
      },
      {
        title: "NET BREAKDOWN BY SIDE",
        headers: ["Side", "Points"],
        rows: Object.entries(netBreakdown.bySide).map(([k, v]) => [k, v]),
      },
      {
        title: "NET BREAKDOWN BY REASON",
        headers: ["Reason", "Points"],
        rows: Object.entries(netBreakdown.byReason).map(([k, v]) => [k, v]),
      },
    ]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `backtest-analysis-${fromDate}_${toDate}.xls`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleSavePreset() {
    const name = window.prompt("Preset name", `Preset ${presets.length + 1}`);
    if (!name?.trim()) return;
    const list = loadPresets().filter((p) => p.name !== name.trim());
    list.push({ name: name.trim(), fromDate, toDate, params: bt });
    savePresets(list);
    setPresets(list.map((p) => p.name));
  }

  function handleLoadPreset(name: string) {
    const found = loadPresets().find((p) => p.name === name);
    if (!found) return;
    setBt(found.params);
    setFromDate(found.fromDate);
    setToDate(found.toDate);
  }

  const summaryStats = stats
    ? ({
        net_profit: stats.net_profit,
        total_trades: stats.total_trades,
        win_rate: `${stats.win_rate}%`,
        profit_factor: stats.profit_factor,
        max_drawdown: stats.max_drawdown,
        expectancy: stats.expectancy,
        avg_win: stats.avg_win,
        avg_loss: stats.avg_loss,
        largest_profit: stats.largest_profit,
        largest_loss: stats.largest_loss,
        final_capital: stats.final_capital,
        gross_profit: stats.gross_profit,
        total_pnl: stats.total_pnl,
        trade_cycles: stats.trade_cycles ?? 0,
        exit_events: stats.exit_events ?? stats.total_trades,
        closed_trades: stats.closed_trades ?? stats.total_trades,
        reentry_cycles: stats.reentry_cycles ?? 0,
        max_averaging: stats.max_averaging_per_cycle ?? 0,
      } as Record<string, string | number>)
    : null;

  return (
    <div className="backtest-premium min-h-full">
      <div className="mx-auto max-w-[1400px] space-y-5 px-4 py-6 pb-12">
        <BtHeader
          onLoadLive={() => d.bootDone && setBt(loadFromDashboard(d))}
          onReset={() => setBt(BT_DEFAULTS)}
          onSavePreset={handleSavePreset}
          onLoadPreset={handleLoadPreset}
          presets={presets}
        />

        <BacktestGuideSection />

        {/* Settings grid */}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <SettingCard icon={Calendar} title="Session" description="Trading session configuration." delay={0.05}>
            <Field label="From Date" hint="Backtest start date">
              <input type="date" className={btInput} value={fromDate} max={toDate} onChange={(e) => setFromDate(e.target.value)} />
            </Field>
            <Field label="To Date" hint="Backtest end date">
              <input type="date" className={btInput} value={toDate} min={fromDate} onChange={(e) => setToDate(e.target.value)} />
            </Field>
            <Field label="Candle" hint="Historical candle interval">
              <div className={cn(btInput, "flex items-center text-slate-400")}>1 minute</div>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start Time" hint="Session open">
                <input type="time" className={btInput} value={bt.startTime} onChange={(e) => patch({ startTime: e.target.value })} />
              </Field>
              <Field label="End Time" hint="Session close">
                <input type="time" className={btInput} value={bt.endTime} onChange={(e) => patch({ endTime: e.target.value })} />
              </Field>
            </div>
            <Field label="Square Off" hint="Auto square-off time">
              <input type="time" className={btInput} value={bt.autoSquareOffTime} onChange={(e) => patch({ autoSquareOffTime: e.target.value })} />
            </Field>
          </SettingCard>

          <SettingCard icon={Zap} title="Entry Settings" description="Configure entry trigger and strike selection." delay={0.1}>
            <Field label="Entry Trigger" hint="Points from day base to trigger entry">
              <NumStepper value={bt.entryTrigger} min={1} onChange={(n) => patch({ entryTrigger: n })} />
            </Field>
            <Field label="Strike Offset" hint="ATM strike offset in points">
              <NumStepper value={bt.strikeOffset} min={50} step={50} onChange={(n) => patch({ strikeOffset: n })} />
            </Field>
            <Field label="Stop Distance" hint="Index stop loss distance">
              <NumStepper value={bt.stopDistance} min={1} onChange={(n) => patch({ stopDistance: n })} />
            </Field>
          </SettingCard>

          <SettingCard icon={Layers} title="Position Management" description="Lots per entry and averaging." delay={0.15}>
            <Field label="Maximum Entries" hint="Max entries per cycle">
              <NumStepper
                value={bt.maxEntries}
                min={1}
                max={20}
                onChange={(n) =>
                  patch({
                    maxEntries: n,
                    entryLots: normalizeEntryLots(bt.entryLots, n, bt.entryLots[0] ?? bt.initialLots, bt.entryLots[1] ?? bt.addLots),
                  })
                }
              />
            </Field>
            <EntryLotsSteppers
              maxEntries={bt.maxEntries}
              entryLots={bt.entryLots}
              onChange={(lots) =>
                patch({
                  entryLots: lots,
                  initialLots: lots[0] ?? bt.initialLots,
                  addLots: lots[1] ?? bt.addLots,
                })
              }
            />
            <Field label="Averaging Gap" hint="Points between average entries">
              <NumStepper value={bt.averagingGap} min={1} onChange={(n) => patch({ averagingGap: n })} />
            </Field>
          </SettingCard>

          <SettingCard icon={Target} title="Target Settings" description="Profit booking and trailing logic." delay={0.2}>
            <Field label="First Entry TP1" hint="Core / initial 2-lot entry target (points)">
              <NumStepper value={bt.firstEntryTp1Points} min={1} onChange={(n) => patch({ firstEntryTp1Points: n })} />
            </Field>
            <Field label="Averaging TP1" hint="TP1 for AVG adds only (points)">
              <NumStepper value={bt.tp1Points} min={1} onChange={(n) => patch({ tp1Points: n })} />
            </Field>
            <Field label="TP2 Trail" hint="Trailing stop after TP1">
              <NumStepper value={bt.tp2Trail} min={1} onChange={(n) => patch({ tp2Trail: n })} />
            </Field>
          </SettingCard>

          <SettingCard icon={Repeat} title="Re-entry" description="Post-TP2 re-entry rules." delay={0.25}>
            <BtToggle label="Enable Re-entry" checked={bt.reEntryEnabled} onChange={(v) => patch({ reEntryEnabled: v })} />
            <Field label="Re-entry Gap" hint="Pullback required before re-entry">
              <NumStepper value={bt.reEntryGap} min={1} onChange={(n) => patch({ reEntryGap: n })} />
            </Field>
            <Field label="Maximum Re-entries" hint="Max re-entries per day">
              <NumStepper value={bt.maxReEntries} min={0} max={10} onChange={(n) => patch({ maxReEntries: n })} />
            </Field>
            <BtToggle label="Allow First Entry" checked={bt.firstEntryEnabled} onChange={(v) => patch({ firstEntryEnabled: v })} />
          </SettingCard>

          <SettingCard icon={Compass} title="Trade Direction" description="Which option sides to trade." delay={0.3}>
            <DirectionRadio value={bt.tradeDirection} onChange={setDirection} />
          </SettingCard>
        </div>

        <RunSection loading={loading} progress={loadProgress} message={message} onRun={() => void loadAndRun()} />

        {!hasRun && !loading ? (
          <div className="flex min-h-[180px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border-subtle)] bg-[var(--surface-muted)] p-8">
            <BarChart3 className="h-10 w-10 text-[var(--text-muted)]" />
            <p className="mt-3 text-sm text-[var(--text-muted)]">Configure parameters and run backtest to view analytics</p>
          </div>
        ) : null}

        {hasRun ? (
          <div className="space-y-5">
            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Performance Summary</h2>
              <SummaryGrid stats={summaryStats} />
            </div>

            <BaseTriggerSection rows={daySummaries} />

            <div className="grid gap-5 xl:grid-cols-2">
              <AdaptiveTimelineSection
                dayDetails={dayDetails}
                selectedDate={chartDate || dayDetails[0]?.date || ""}
                onSelectDate={setChartDate}
              />
              {chartDay ? (
                <PlannedLevelsSection levels={chartDay.plannedLevels} date={chartDay.date} />
              ) : null}
            </div>

            {chartDay ? (
              <div>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-slate-500">Chart day:</span>
                  <select
                    className="h-8 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-2 text-xs text-[var(--text-primary)]"
                    value={chartDay.date}
                    onChange={(e) => setChartDate(e.target.value)}
                  >
                    {dayDetails.map((d) => (
                      <option key={d.date} value={d.date}>{d.date}</option>
                    ))}
                  </select>
                </div>
                <PriceChartSection
                  candles={chartDay.candles}
                  levels={{ base: chartDay.base, callTrigger: chartDay.callTrigger, putTrigger: chartDay.putTrigger }}
                  timeline={chartDay.timeline}
                  date={chartDay.date}
                />
              </div>
            ) : null}

            <NetPointBreakdown data={netBreakdown} />

            <AnalyticsPanel
              daySummaries={daySummaries.map((d) => ({ date: d.date, points: d.points }))}
              equityCurve={equityCurve}
              drawdownCurve={drawdownCurve}
              monthly={analysis.monthly}
              winCount={stats?.winning_trades ?? 0}
              lossCount={stats?.losing_trades ?? 0}
            />

            <TradeRecordSection tableRows={tradeTableRows} onExportExcel={exportExcel} onExportCsv={exportCsv} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
