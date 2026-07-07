"use client";

import { Download, Loader2, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { GridBacktestChart } from "@/components/strategy4/grid-backtest-chart";
import { CardTitle, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { runBreakoutBacktest } from "@/lib/strategy4/api";
import {
  DEFAULT_BACKTEST_CONFIG,
  loadBacktestConfig,
  saveBacktestConfig,
  type BreakoutBacktestResult,
  type BreakoutRoundTrip,
  type MarketKey,
  type Strategy4Config,
} from "@/lib/strategy4/types";
import { cn } from "@/components/ui";

const MARKETS: { value: MarketKey; label: string }[] = [
  { value: "CRUDE_OIL", label: "Crude Oil" },
  { value: "NATURAL_GAS", label: "Natural Gas" },
  { value: "SILVER_MICRO", label: "Silver Micro" },
];

const LOT_OPTIONS = [1, 2, 4, 5, 6, 10];
const MAX_BACKTEST_DAYS = 31;

function numInput(v: number): string {
  if (!Number.isFinite(v) || v === 0) return "";
  return String(v);
}

function parseNum(raw: string): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function fmtDate(d: string) {
  if (!d) return "-";
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${y}`;
}

function fmtPx(n: number) {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtTime(raw: string | undefined | null) {
  if (!raw) return "—";
  const normalized = raw.replace("T", " ");
  const hhmmss = normalized.slice(11, 19);
  if (hhmmss) return hhmmss;
  const hhmm = normalized.slice(11, 16);
  return hhmm || raw;
}

function tradeHistoryRow(t: BreakoutRoundTrip) {
  return [
    fmtDate(t.date),
    t.entryType,
    t.side,
    t.entryTimeLabel || fmtTime(t.entryTime),
    t.entryPrice,
    t.tpPrice ?? "",
    t.slPrice ?? "",
    t.exitTimeLabel || fmtTime(t.exitTime),
    t.exitPrice,
    t.exitReason,
    t.durationMinutes != null ? `${t.durationMinutes}m` : "",
    t.lots,
    t.tradePnl,
    t.runningDayPnl,
  ];
}

function csvCell(v: string | number | null | undefined) {
  const s = v == null ? "" : String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function dateRange(from: string, to: string) {
  const out: string[] = [];
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  for (let cur = new Date(start); cur <= end; cur.setDate(cur.getDate() + 1)) {
    out.push(cur.toISOString().slice(0, 10));
  }
  return out;
}

function ScrollTable({ children, maxH = "max-h-[420px]" }: { children: React.ReactNode; maxH?: string }) {
  return <div className={cn("overflow-auto rounded-lg border border-[var(--border-subtle)]", maxH)}>{children}</div>;
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium">{children}</th>;
}

export function Strategy4BacktestView() {
  const [cfg, setCfg] = useState<Strategy4Config>(DEFAULT_BACKTEST_CONFIG);
  const [fromDate, setFromDate] = useState(daysAgoIso(4));
  const [toDate, setToDate] = useState(todayIso());
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<BreakoutBacktestResult | null>(null);
  const [selectedDay, setSelectedDay] = useState<string>("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setCfg(loadBacktestConfig());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveBacktestConfig(cfg);
  }, [cfg, hydrated]);

  const summary = result?.summary;
  const roundTrips = result?.roundTrips ?? [];
  const dailyReference = result?.dailyReference ?? [];
  const dailyCharts = result?.dailyCharts ?? [];
  const daySummaries = result?.daySummaries ?? [];
  const executionPolicy = result?.executionPolicy;

  const activeChart = useMemo(() => {
    if (!dailyCharts.length) return null;
    return dailyCharts.find((d) => d.date === selectedDay) ?? dailyCharts[dailyCharts.length - 1];
  }, [dailyCharts, selectedDay]);

  const chartCandles = activeChart?.candles ?? result?.candles ?? [];
  const chartTrades = activeChart?.trades ?? result?.chartTrades ?? [];
  const chartLevels = activeChart?.levels ?? result?.chartLevels ?? [];

  const subtitle = useMemo(() => {
    if (!result) return "MCX breakout backtest — same rules as live trading";
    return `${result.instrument || result.market} · ${fmtDate(result.fromDate)} → ${fmtDate(result.toDate)}`;
  }, [result]);

  async function handleRun() {
    if (fromDate > toDate) {
      setMessage("From date must be on or before To date.");
      return;
    }
    const dates = dateRange(fromDate, toDate);
    if (dates.length > MAX_BACKTEST_DAYS) {
      setMessage(`Maximum ${MAX_BACKTEST_DAYS} days per backtest.`);
      return;
    }
    if (cfg.breakoutDistance <= 0 || cfg.takeProfit <= 0 || cfg.stopLoss <= 0 || cfg.lotSize <= 0) {
      setMessage("Lot size, breakout distance, TP and SL must be greater than zero.");
      return;
    }

    setLoading(true);
    setMessage("Fetching candles and running breakout simulation…");
    setResult(null);
    const t0 = performance.now();

    try {
      const data = await runBreakoutBacktest({ fromDate, toDate, ...cfg });
      setResult(data);
      const lastDay = data.dailyCharts?.[data.dailyCharts.length - 1]?.date ?? "";
      setSelectedDay(lastDay);
      const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
      setMessage(
        `${data.daysRun} day(s) · ${data.summary.totalTrades} trade(s) · P&L ${fmtPx(data.summary.totalPnl)} · ${elapsed}s` +
          (data.skippedDays > 0
            ? ` · ${data.skippedDays} day(s) skipped${data.skippedDates?.length ? `: ${data.skippedDates.join(", ")}` : ""}`
            : "") +
          (data.chartSubtitle ? ` · ${data.chartSubtitle}` : ""),
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Backtest failed.");
    } finally {
      setLoading(false);
    }
  }

  function exportExcel() {
    if (!result) return;
    const rows: (string | number)[][] = [
      ["MCX Breakout Backtest Report"],
      ["From Date", fmtDate(fromDate)],
      ["To Date", fmtDate(toDate)],
      ["Market", cfg.market],
      ["Instrument", result.instrument],
      ["Lot Size", cfg.lotSize],
      ["Breakout Distance", cfg.breakoutDistance],
      ["Take Profit", cfg.takeProfit],
      ["Stop Loss", cfg.stopLoss],
      ["Session", `${cfg.startTime} – ${cfg.endTime}`],
      [],
      ["Summary"],
      ["Total Trades", result.summary.totalTrades],
      ["Total P&L", result.summary.totalPnl],
      ["Win Days", result.summary.winDays],
      ["Loss Days", result.summary.lossDays],
      [],
      ["Day Summary"],
      ["Date", "Trades", "Day P&L", "Phase", "Ref Price", "Candles"],
      ...dailyReference.map((r) => [
        fmtDate(r.date),
        r.referenceClose,
        r.buyTrigger,
        r.sellTrigger,
        r.initialDirection,
        r.result,
        r.pnl ?? "",
      ]),
      [],
      ["Trade History"],
      [
        "Date",
        "Trade",
        "Direction",
        "Entry Time",
        "Entry Price",
        "TP",
        "SL",
        "Exit Time",
        "Exit Price",
        "Exit Reason",
        "Duration",
        "Lots",
        "Trade P&L",
        "Running Day P&L",
      ],
      ...roundTrips.map(tradeHistoryRow),
    ];

    const csv = rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "application/vnd.ms-excel;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mcx-breakout-backtest-${fromDate}_to_${toDate}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-10">
      <PageHeader
        title="Backtest"
        subtitle={subtitle}
        action={
          result ? (
            <button
              type="button"
              onClick={exportExcel}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)]"
            >
              <Download className="h-4 w-4" />
              Export CSV
            </button>
          ) : null
        }
      />

      <PremiumCard className="!p-4">
        <CardTitle
          title="Backtest Setup"
          action={
            <button
              type="button"
              onClick={() => void handleRun()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run Backtest
            </button>
          }
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <FloatingField id="bt-from" label="From Date" type="date" value={fromDate} onChange={setFromDate} />
          <FloatingField id="bt-to" label="To Date" type="date" value={toDate} onChange={setToDate} />
          <div className="rounded-[var(--radius-input)] border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--accent)]">Candle</p>
            <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">1 minute</p>
          </div>
          <FloatingField
            id="bt-start"
            label="Start Time (Reference)"
            type="time"
            value={cfg.startTime}
            onChange={(v) => setCfg((c) => ({ ...c, startTime: v }))}
          />
          <FloatingField
            id="bt-end"
            label="End Time (MCX)"
            type="time"
            value={cfg.endTime}
            onChange={(v) => setCfg((c) => ({ ...c, endTime: v }))}
          />
        </div>
        {message ? (
          <p
            className={cn(
              "mt-3 text-sm",
              message.includes("failed") || message.includes("Maximum") || message.includes("must be")
                ? "text-[var(--danger)]"
                : "text-[var(--text-secondary)]",
            )}
          >
            {message}
          </p>
        ) : null}
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Strategy Parameters" subtitle="Independent from live settings." />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block space-y-2 sm:col-span-2">
            <span className="text-sm font-medium text-[var(--text-secondary)]">Market</span>
            <select
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
              value={cfg.market}
              onChange={(e) => setCfg((c) => ({ ...c, market: e.target.value as MarketKey }))}
            >
              {MARKETS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-2">
            <span className="text-sm font-medium text-[var(--text-secondary)]">Lot Size</span>
            <select
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
              value={cfg.lotSize}
              onChange={(e) => setCfg((c) => ({ ...c, lotSize: Number(e.target.value) }))}
            >
              {LOT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <FloatingField
            id="bt-bd"
            label="Breakout Distance"
            type="number"
            step="0.01"
            value={numInput(cfg.breakoutDistance)}
            onChange={(v) => setCfg((c) => ({ ...c, breakoutDistance: parseNum(v) }))}
          />
          <FloatingField
            id="bt-tp"
            label="Take Profit (Points)"
            type="number"
            step="0.01"
            value={numInput(cfg.takeProfit)}
            onChange={(v) => setCfg((c) => ({ ...c, takeProfit: parseNum(v) }))}
          />
          <FloatingField
            id="bt-sl"
            label="Stop Loss (Points)"
            type="number"
            step="0.01"
            value={numInput(cfg.stopLoss)}
            onChange={(v) => setCfg((c) => ({ ...c, stopLoss: parseNum(v) }))}
          />
        </div>
      </PremiumCard>

      {summary ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: "Total P&L", value: fmtPx(summary.totalPnl), tone: summary.totalPnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]" },
              { label: "Trades", value: String(summary.totalTrades) },
              { label: "Win Rate", value: `${summary.winRate}%` },
              { label: "Profit Factor", value: String(summary.profitFactor) },
            ].map((card) => (
              <PremiumCard key={card.label} className="!p-4">
                <p className="text-xs text-[var(--text-muted)]">{card.label}</p>
                <p className={cn("mt-1 text-xl font-semibold", card.tone ?? "text-[var(--text-primary)]")}>{card.value}</p>
              </PremiumCard>
            ))}
          </div>

          <PremiumCard className="!p-4">
            <CardTitle title="Backtest Summary" subtitle="Aggregate statistics across all trading days" />
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-sm">
              {[
                ["Trading Days", summary.totalTradingDays],
                ["Skipped Days", summary.skippedDays],
                ["Buy / Sell Entries", `${summary.buyTrades} / ${summary.sellTrades}`],
                ["Reverse Trades", summary.reverseTrades],
                ["Win / Loss Initial", `${summary.winningInitialTrades} / ${summary.losingInitialTrades}`],
                ["Win / Loss Reverse", `${summary.winningReverseTrades} / ${summary.losingReverseTrades}`],
                ["Breakeven Initial / Reverse", `${summary.breakevenInitialTrades ?? 0} / ${summary.breakevenReverseTrades ?? 0}`],
                ["Avg Win / Avg Loss", `${fmtPx(summary.averageWin)} / ${fmtPx(summary.averageLoss)}`],
                ["Max Drawdown", fmtPx(summary.maxDrawdown)],
                ["Expectancy", fmtPx(summary.expectancy)],
                ["Avg Duration (min)", summary.averageTradeDurationMinutes],
                ["Win / Loss Days", `${summary.winDays} / ${summary.lossDays}`],
              ].map(([k, v]) => (
                <div key={String(k)} className="rounded-lg border border-[var(--border-subtle)] px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{k}</p>
                  <p className="font-medium text-[var(--text-primary)]">{v}</p>
                </div>
              ))}
            </div>
            {executionPolicy ? (
              <div className="mt-3 rounded-lg bg-[var(--surface-muted)] px-3 py-2 text-xs text-[var(--text-secondary)]">
                <p className="font-medium text-[var(--text-primary)]">Execution policy (deterministic OHLC rules)</p>
                <ul className="mt-1 list-disc space-y-1 pl-4">
                  {Object.entries(executionPolicy).map(([k, v]) => (
                    <li key={k}>
                      <span className="font-medium">{k}:</span> {v}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </PremiumCard>

          <PremiumCard className="!p-4">
            <CardTitle title="Daily Reference Levels" subtitle={`Reference candle OHLC at ${cfg.startTime}`} />
            <ScrollTable>
              <table className="w-full min-w-[1200px] text-left text-sm">
                <thead className="text-xs text-[var(--text-muted)]">
                  <tr className="border-b border-[var(--border-subtle)]">
                    <Th>Date</Th>
                    <Th>Ref Time</Th>
                    <Th>Open</Th>
                    <Th>High</Th>
                    <Th>Low</Th>
                    <Th>Close</Th>
                    <Th>Buy @</Th>
                    <Th>Buy Touch</Th>
                    <Th>High@Touch</Th>
                    <Th>Sell @</Th>
                    <Th>Sell Touch</Th>
                    <Th>Low@Touch</Th>
                    <Th>Direction</Th>
                    <Th>Result</Th>
                    <Th>Day P&L</Th>
                  </tr>
                </thead>
                <tbody>
                  {dailyReference.map((r) => (
                    <tr key={r.date} className="border-b border-[var(--border-subtle)] text-[var(--text-secondary)]">
                      <td className="px-3 py-2 font-medium text-[var(--text-primary)]">{fmtDate(r.date)}</td>
                      <td className="px-3 py-2">{r.referenceCandleTime}</td>
                      <td className="px-3 py-2 font-mono">{r.referenceOpen ? fmtPx(r.referenceOpen) : "—"}</td>
                      <td className="px-3 py-2 font-mono">{r.referenceHigh ? fmtPx(r.referenceHigh) : "—"}</td>
                      <td className="px-3 py-2 font-mono">{r.referenceLow ? fmtPx(r.referenceLow) : "—"}</td>
                      <td className="px-3 py-2 font-mono font-semibold">{fmtPx(r.referenceClose)}</td>
                      <td className="px-3 py-2 font-mono">{fmtPx(r.buyTrigger)}</td>
                      <td className="px-3 py-2">{r.buyTriggerTime}</td>
                      <td className="px-3 py-2 font-mono">{r.buyTriggerTouchHigh != null ? fmtPx(r.buyTriggerTouchHigh) : "—"}</td>
                      <td className="px-3 py-2 font-mono">{fmtPx(r.sellTrigger)}</td>
                      <td className="px-3 py-2">{r.sellTriggerTime}</td>
                      <td className="px-3 py-2 font-mono">{r.sellTriggerTouchLow != null ? fmtPx(r.sellTriggerTouchLow) : "—"}</td>
                      <td className="px-3 py-2">{r.initialDirection}</td>
                      <td className="px-3 py-2 text-xs">{r.result}</td>
                      <td className={cn("px-3 py-2 font-mono font-semibold", (r.pnl ?? 0) >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]")}>
                        {fmtPx(r.pnl ?? 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollTable>
          </PremiumCard>
        </>
      ) : null}

      {activeChart ? (
        <PremiumCard className="!p-4">
          <CardTitle
            title="Daily Timeline"
            subtitle={`${fmtDate(activeChart.date)} · ${activeChart.result ?? ""}`}
            action={
              dailyCharts.length > 1 ? (
                <select
                  className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs"
                  value={selectedDay}
                  onChange={(e) => setSelectedDay(e.target.value)}
                >
                  {dailyCharts.map((d) => (
                    <option key={d.date} value={d.date}>
                      {fmtDate(d.date)}
                    </option>
                  ))}
                </select>
              ) : null
            }
          />
          <div className="mt-3 space-y-2 border-l-2 border-[var(--accent)] pl-4">
            {(activeChart.timeline ?? []).map((step, i) => (
              <div key={i} className="text-sm">
                <p className="font-mono text-xs text-[var(--text-muted)]">{step.time || "—"}</p>
                <p className="font-medium text-[var(--text-primary)]">{step.label}</p>
                {step.detail ? <p className="text-[var(--text-secondary)]">{step.detail}</p> : null}
              </div>
            ))}
          </div>
        </PremiumCard>
      ) : null}

      <PremiumCard className="!p-4">
        <CardTitle
          title="Price Chart & Trades"
          subtitle={result?.chartSubtitle || "Candles with colored levels and entry/exit markers"}
          action={
            dailyCharts.length > 1 ? (
              <select
                className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs"
                value={selectedDay}
                onChange={(e) => setSelectedDay(e.target.value)}
              >
                {dailyCharts.map((d) => (
                  <option key={d.date} value={d.date}>
                    {fmtDate(d.date)}
                  </option>
                ))}
              </select>
            ) : null
          }
        />
        <GridBacktestChart candles={chartCandles} trades={chartTrades} gridLevels={chartLevels} referencePrice={activeChart?.referenceClose ?? result?.referencePrice} />
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Day-wise Analysis" subtitle={daySummaries.length ? `${daySummaries.length} day(s)` : "Run backtest first"} />
        <ScrollTable>
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-[var(--text-muted)]">
              <tr className="border-b border-[var(--border-subtle)]">
                <Th>Date</Th>
                <Th>Trades</Th>
                <Th>Day P&L</Th>
                <Th>Phase</Th>
                <Th>Ref</Th>
                <Th>Candles</Th>
              </tr>
            </thead>
            <tbody>
              {daySummaries.map((r) => (
                <tr key={r.date} className="border-b border-[var(--border-subtle)] text-[var(--text-secondary)]">
                  <td className="px-3 py-2 font-medium text-[var(--text-primary)]">{fmtDate(r.date)}</td>
                  <td className="px-3 py-2">{r.trades}</td>
                  <td className={cn("px-3 py-2 font-mono font-semibold", r.pnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]")}>
                    {fmtPx(r.pnl)}
                  </td>
                  <td className="px-3 py-2">{r.phase ?? "—"}</td>
                  <td className="px-3 py-2">{r.referencePrice ? fmtPx(r.referencePrice) : "—"}</td>
                  <td className="px-3 py-2">{r.candles}</td>
                </tr>
              ))}
              {!daySummaries.length ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-[var(--text-muted)]">
                    No data yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </ScrollTable>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Trade History" subtitle="One row per completed trade — initial and reverse legs" />
        <ScrollTable maxH="max-h-[520px]">
          <table className="w-full min-w-[1280px] text-left text-sm">
            <thead className="text-xs text-[var(--text-muted)]">
              <tr className="border-b border-[var(--border-subtle)]">
                <Th>Date</Th>
                <Th>Trade</Th>
                <Th>Direction</Th>
                <Th>Entry Time</Th>
                <Th>Entry</Th>
                <Th>TP</Th>
                <Th>SL</Th>
                <Th>Exit Time</Th>
                <Th>Exit</Th>
                <Th>Exit Reason</Th>
                <Th>Duration</Th>
                <Th>Lots</Th>
                <Th>Trade P&L</Th>
                <Th>Day P&L</Th>
              </tr>
            </thead>
            <tbody>
              {roundTrips.map((t) => (
                <tr key={`${t.date}-${t.id}`} className="border-b border-[var(--border-subtle)] text-[var(--text-secondary)]">
                  <td className="px-3 py-2 font-medium text-[var(--text-primary)]">{fmtDate(t.date)}</td>
                  <td className="px-3 py-2">{t.entryType}</td>
                  <td className="px-3 py-2 font-medium">{t.side}</td>
                  <td className="px-3 py-2 font-mono text-xs">{t.entryTimeLabel || fmtTime(t.entryTime)}</td>
                  <td className="px-3 py-2 font-mono">{fmtPx(t.entryPrice)}</td>
                  <td className="px-3 py-2 font-mono">{t.tpPrice != null && t.tpPrice > 0 ? fmtPx(t.tpPrice) : "—"}</td>
                  <td className="px-3 py-2 font-mono">{t.slPrice != null && t.slPrice > 0 ? fmtPx(t.slPrice) : "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{t.exitTimeLabel || fmtTime(t.exitTime)}</td>
                  <td className="px-3 py-2 font-mono">{fmtPx(t.exitPrice)}</td>
                  <td className="px-3 py-2">{t.exitReason}</td>
                  <td className="px-3 py-2">{t.durationMinutes != null ? `${t.durationMinutes}m` : "—"}</td>
                  <td className="px-3 py-2">{t.lots}</td>
                  <td className={cn("px-3 py-2 font-mono font-semibold", t.tradePnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]")}>
                    {t.tradePnl >= 0 ? "+" : ""}
                    {fmtPx(t.tradePnl)}
                  </td>
                  <td className={cn("px-3 py-2 font-mono font-semibold", t.runningDayPnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]")}>
                    {t.runningDayPnl >= 0 ? "+" : ""}
                    {fmtPx(t.runningDayPnl)}
                  </td>
                </tr>
              ))}
              {!roundTrips.length ? (
                <tr>
                  <td colSpan={14} className="px-3 py-6 text-center text-[var(--text-muted)]">
                    Run backtest to see completed trades.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </ScrollTable>
      </PremiumCard>
    </div>
  );
}
