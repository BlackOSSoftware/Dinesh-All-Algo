"use client";

import { Download, Loader2, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { BreakoutBacktestChart } from "@/components/strategy3/breakout-backtest-chart";
import { CardTitle, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { fetchSettings, runBreakoutBacktest } from "@/lib/strategy3/api";
import {
  DEFAULT_CONFIG,
  configToApi,
  loadBacktestConfig,
  premiumTierLabel,
  saveBacktestConfig,
  windowTimes,
  type BreakoutBacktestResult,
  type BreakoutBacktestTrade,
  type BreakoutChartSeries,
  type ExpiryInfo,
  type ProductType,
  type Strategy3Config,
} from "@/lib/strategy3/types";
import { cn } from "@/components/ui";

const MAX_BACKTEST_DAYS = 90;

function numInput(v: number): string {
  if (!Number.isFinite(v) || v === 0) return "";
  return String(v);
}

function parseNum(raw: string): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function fmtDate(d: string) {
  if (!d) return "-";
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${y}`;
}

function fmtPx(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtTradeTime(t: BreakoutBacktestTrade, field: "entry" | "exit"): string {
  const status = String(t.status ?? t.exitReason ?? "");
  if (status === "SKIPPED") return "Skipped";
  if (status === "NO_TRADE") return "N/A";
  if (status === "PENDING_ENTRY") return field === "entry" ? "Not triggered" : "N/A";
  return field === "entry" ? (t.entryTime || "—") : (t.exitTimeFormatted || "—");
}

function fmtTradePrice(t: BreakoutBacktestTrade, field: "entry" | "exit"): string {
  const status = String(t.status ?? t.exitReason ?? "");
  if (status === "SKIPPED") return "—";
  if (status === "NO_TRADE") return "—";
  if (status === "PENDING_ENTRY") return field === "entry" ? fmtPx(t.entryPrice ?? t.triggerPrice) : "—";
  return field === "entry" ? fmtPx(t.entryPrice) : fmtPx(t.exitPrice);
}

function csvCell(v: string | number | null | undefined) {
  const s = v == null ? "" : String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) return `"${s.replace(/"/g, '""')}"`;
  return s;
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

function exportTradesExcel(trades: BreakoutBacktestTrade[]) {
  const headers = [
    "S.No",
    "Date",
    "Side",
    "Window",
    "Strike",
    "Symbol",
    "Entry Time",
    "Exit Time",
    "Entry Price",
    "Exit Price",
    "Lots",
    "Size Multiplier",
    "Effective Qty",
    "Exit Reason",
    "Points",
    "P&L",
    "Details",
  ];
  const rows = trades.map((t) => [
    t.serialNo ?? t.id,
    t.date,
    t.sideLabel ?? t.side,
    t.window ?? "",
    t.strike ?? "",
    t.symbol ?? "",
    t.entryTime ?? "",
    t.exitTimeFormatted ?? "",
    t.entryPrice ?? "",
    t.exitPrice ?? "",
    t.lots ?? "",
    t.sizeMultiplier ?? 1,
    t.effectiveQuantity ?? t.lots ?? "",
    t.exitReason ?? t.status ?? "",
    t.points ?? "",
    t.pnl ?? "",
    t.details ?? t.message ?? "",
  ]);
  const csv = [headers, ...rows].map((r) => r.map(csvCell).join(",")).join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `strategy3-backtest-${todayIso()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function Strategy3BacktestView() {
  const [cfg, setCfg] = useState<Strategy3Config>(DEFAULT_CONFIG);
  const [expiryInfo, setExpiryInfo] = useState<ExpiryInfo | null>(null);
  const [fromDate, setFromDate] = useState(daysAgoIso(MAX_BACKTEST_DAYS - 1));
  const [toDate, setToDate] = useState(todayIso());
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<BreakoutBacktestResult | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [selectedDay, setSelectedDay] = useState("");
  const [selectedChartId, setSelectedChartId] = useState("");

  const windows = useMemo(() => windowTimes(cfg), [cfg]);

  useEffect(() => {
    setCfg(loadBacktestConfig());
    setHydrated(true);
    void fetchSettings().then((res) => {
      if (res.expiry_info) setExpiryInfo(res.expiry_info as ExpiryInfo);
    });
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveBacktestConfig(cfg);
  }, [cfg, hydrated]);

  const dayDetails = result?.dayDetails ?? [];
  const analysis = result?.analysis;
  const tradeRecords = result?.tradeRecords ?? result?.trades ?? [];
  const debugRows = result?.debugRows ?? [];

  const activeDay = useMemo(
    () => dayDetails.find((d) => d.date === selectedDay) ?? dayDetails[0] ?? null,
    [dayDetails, selectedDay],
  );

  const activeChart: BreakoutChartSeries | null = useMemo(() => {
    const list = activeDay?.chartSeries ?? [];
    if (!list.length) return null;
    return list.find((s) => s.id === selectedChartId) ?? list[0];
  }, [activeDay, selectedChartId]);

  const chartTrades = useMemo(() => {
    if (!activeChart) return [];
    return tradeRecords.filter((t) => t.chartId === activeChart.id && t.status === "CLOSED");
  }, [tradeRecords, activeChart]);

  useEffect(() => {
    if (!result?.dayDetails?.length) return;
    const first = result.dayDetails[0].date;
    setSelectedDay(first);
    const cs = result.dayDetails[0].chartSeries?.[0]?.id ?? "";
    setSelectedChartId(cs);
  }, [result]);

  useEffect(() => {
    if (!activeDay?.chartSeries?.length) return;
    if (!activeDay.chartSeries.some((s) => s.id === selectedChartId)) {
      setSelectedChartId(activeDay.chartSeries[0].id);
    }
  }, [activeDay, selectedChartId]);

  const subtitle = useMemo(() => {
    if (!result) return "SENSEX expiry-day ITM breakout — same algo as live settings";
    return `${fmtDate(result.fromDate)} → ${fmtDate(result.toDate)} · ${result.daysRun} expiry day(s)`;
  }, [result]);

  async function handleRun() {
    if (fromDate > toDate) {
      setMessage("From date must be on or before To date.");
      return;
    }
    if (dateRange(fromDate, toDate).length > MAX_BACKTEST_DAYS) {
      setMessage(`Maximum ${MAX_BACKTEST_DAYS} calendar days per run. Only expiry sessions are simulated.`);
      return;
    }
    setLoading(true);
    setMessage("Fetching StocksRin historical data and running backtest…");
    setResult(null);
    const t0 = performance.now();
    try {
      const res = await runBreakoutBacktest({ fromDate, toDate, config: configToApi(cfg) });
      setResult(res);
      const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
      setMessage(
        `${res.message} · ${elapsed}s` +
          (res.skippedDays > 0 ? ` · ${res.skippedDays} non-expiry day(s) skipped` : "") +
          (res.failedDays && res.failedDays > 0
            ? ` · ${res.failedDays} day(s) failed — see errors below`
            : "") +
          (res.sessionError ? ` · ${res.sessionError}` : ""),
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Backtest failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-10">
      <PageHeader title="Backtest" subtitle={subtitle} />

      <PremiumCard className="!p-4">
        <CardTitle title="Date Range" subtitle="Backtest runs only on auto-detected SENSEX expiry days in this range" />
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FloatingField id="bt-from" label="Start Date" type="date" value={fromDate} onChange={setFromDate} />
          <FloatingField id="bt-to" label="End Date" type="date" value={toDate} onChange={setToDate} />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Strategy Settings" subtitle="Same parameters as Strategy Settings page" />
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FloatingField id="bt-start" label="First Window Start" type="time" value={cfg.startTime} onChange={(v) => setCfg((c) => ({ ...c, startTime: v }))} />
          <FloatingField id="bt-wc" label="Number of Windows" type="number" value={numInput(cfg.windowCount)} onChange={(v) => setCfg((c) => ({ ...c, windowCount: parseNum(v) }))} />
          <FloatingField id="bt-gap" label="Gap Between Windows (min)" type="number" value={numInput(cfg.windowGapMinutes)} onChange={(v) => setCfg((c) => ({ ...c, windowGapMinutes: parseNum(v) }))} />
          <FloatingField id="bt-tf" label="Candle Timeframe (min)" type="number" value="10" onChange={() => {}} disabled />
          <FloatingField id="bt-target" label="Target (%)" type="number" value={numInput(cfg.targetPercent)} onChange={(v) => setCfg((c) => ({ ...c, targetPercent: parseNum(v) }))} />
          <FloatingField id="bt-sl" label="Stop Loss (%)" type="number" value={numInput(cfg.stopLossPercent)} onChange={(v) => setCfg((c) => ({ ...c, stopLossPercent: parseNum(v) }))} />
          <FloatingField id="bt-qty" label="Quantity (lots)" type="number" value={numInput(cfg.quantity)} onChange={(v) => setCfg((c) => ({ ...c, quantity: parseNum(v) }))} />
          <label className="block space-y-2">
            <span className="text-sm font-medium text-[var(--text-secondary)]">Product Type</span>
            <select className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm" value={cfg.productType} onChange={(e) => setCfg((c) => ({ ...c, productType: e.target.value as ProductType }))}>
              <option value="MIS">MIS (Intraday)</option>
              <option value="NRML">NRML (Carry Forward)</option>
            </select>
          </label>
        </div>
        <p className="mt-3 text-xs text-[var(--text-muted)]">
          Loss recovery rule: after each losing trade, next trade size multiplier doubles. `Lots` stays fixed to your base setting, and the multiplier resets to `1x` after a non-loss trade.
        </p>
        <label className="mt-3 flex items-center gap-2">
          <input type="checkbox" checked={cfg.expiryDayOnly} onChange={(e) => setCfg((c) => ({ ...c, expiryDayOnly: e.target.checked }))} className="h-4 w-4" />
          <span className="text-sm text-[var(--text-secondary)]">Run only on SENSEX expiry day</span>
        </label>
        {cfg.expiryDayOnly && expiryInfo ? (
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            Auto expiry: {expiryInfo.currentWeekExpiryLabel} · Next: {expiryInfo.nextExpiryLabel}
          </p>
        ) : null}
        <p className="mt-2 text-xs text-[var(--text-muted)]">Windows: {windows.join(" → ")}</p>

        <div className="mt-4 overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-[var(--surface-muted)]">
              <tr>
                <th className="px-3 py-2">Premium Close</th>
                <th className="px-3 py-2">Entry %</th>
              </tr>
            </thead>
            <tbody>
              {cfg.premiumTiers.map((tier, i) => (
                <tr key={i} className="border-t border-[var(--border-subtle)]">
                  <td className="px-3 py-2">{premiumTierLabel(cfg.premiumTiers, i)}</td>
                  <td className="px-3 py-2">
                    <input type="number" value={tier.entryPercent} onChange={(e) => setCfg((c) => ({ ...c, premiumTiers: c.premiumTiers.map((t, j) => (j === i ? { ...t, entryPercent: parseNum(e.target.value) } : t)) }))} className="w-20 rounded border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-2 py-1 tabular-nums" />
                    <span className="ml-1">%</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <button type="button" disabled={loading} onClick={() => void handleRun()} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-60">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {loading ? "Running…" : "Run Backtest"}
        </button>
        {message ? <p className="mt-3 text-sm text-[var(--text-secondary)]">{message}</p> : null}
        {result?.daySummaries?.some((d) => d.error) ? (
          <div className="mt-3 space-y-2 rounded-lg border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
            {result.daySummaries.filter((d) => d.error).map((d) => (
              <div key={d.date}>
                <p>
                  <span className="font-medium">{fmtDate(d.date)}:</span> {d.error}
                </p>
                {d.candleDebug ? (
                  <p className="mt-1 font-mono text-[10px] text-[var(--text-muted)]">
                    Loaded {String(d.candleDebug.candleCount ?? 0)} candles · token {String(d.candleDebug.symboltoken ?? "—")} · {String(d.candleDebug.fromdate ?? "")} → {String(d.candleDebug.todate ?? "")}
                    {d.candleDebug.firstCandleTime ? ` · first ${String(d.candleDebug.firstCandleTime).slice(11, 16)}` : ""}
                    {d.candleDebug.lastCandleTime ? ` · last ${String(d.candleDebug.lastCandleTime).slice(11, 16)}` : ""}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
      </PremiumCard>

      {result && analysis ? (
        <>
          <PremiumCard className="!p-4">
            <CardTitle title="Points Breakdown & Analysis" />
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ["TP Hit", analysis.tpHits],
                ["SL Hit", analysis.slHits],
                ["Session End (EOD)", analysis.eodExits],
                ["Pending (not filled)", analysis.pending],
                ["No Trade", analysis.noTrade],
                ["Token Not Found", analysis.tokenNotFound ?? 0],
                ["Data Errors", analysis.dataErrors ?? 0],
                ["Skipped Windows", analysis.skipped],
                ["Win Trades", analysis.winTrades],
                ["Loss Trades", analysis.lossTrades],
                ["Total Points", fmtPx(analysis.totalPoints)],
                ["Total P&L (lots)", fmtPx(analysis.totalPnl)],
                ["Gross Profit", fmtPx(analysis.grossProfit)],
                ["Gross Loss", fmtPx(analysis.grossLoss)],
              ].map(([label, val]) => (
                <div key={String(label)} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</p>
                  <p className={cn("mt-1 text-lg font-semibold tabular-nums", typeof val === "number" && val < 0 ? "text-[var(--danger)]" : "")}>{val}</p>
                </div>
              ))}
            </div>
          </PremiumCard>

          <PremiumCard className="!p-4">
            <CardTitle title="Base & Trigger" subtitle="Reference candle close, ITM strikes, premium base and buy-stop trigger per window" />
            <div className="mt-3 flex flex-wrap gap-3">
              <label className="text-sm">
                <span className="text-[var(--text-muted)]">Expiry day</span>
                <select className="ml-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-3 py-1.5 text-sm" value={selectedDay} onChange={(e) => setSelectedDay(e.target.value)}>
                  {dayDetails.map((d) => (
                    <option key={d.date} value={d.date}>{fmtDate(d.date)} · P&L {fmtPx(d.pnl)}</option>
                  ))}
                </select>
              </label>
            </div>
            {activeDay?.error ? (
              <p className="mt-3 rounded-lg border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
                {activeDay.error}
              </p>
            ) : null}
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-[var(--surface-muted)]">
                  <tr>
                    {["Window", "SENSEX Ref", "Leg", "Strike", "Premium (Base)", "Entry %", "Trigger", "TP", "SL", "Status"].map((h) => (
                      <th key={h} className="px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(activeDay?.setups ?? []).flatMap((s) => [
                    <tr key={`${s.window}-ce`} className="border-t border-[var(--border-subtle)]">
                      <td className="px-2 py-2">{s.window}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.referenceClose)}</td>
                      <td className="px-2 py-2">Call</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.ce.strike)}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.ce.premiumClose)}</td>
                      <td className="px-2 py-2">{s.ce.entryPct != null ? `${s.ce.entryPct}%` : "—"}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.ce.triggerPrice)}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.ce.targetPrice)}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.ce.stopPrice)}</td>
                      <td className="px-2 py-2">{s.ce.tradable ? "Eligible" : s.ce.skipReason ?? "No trade"}</td>
                    </tr>,
                    <tr key={`${s.window}-pe`} className="border-t border-[var(--border-subtle)]">
                      <td className="px-2 py-2">{s.window}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.referenceClose)}</td>
                      <td className="px-2 py-2">Put</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.pe.strike)}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.pe.premiumClose)}</td>
                      <td className="px-2 py-2">{s.pe.entryPct != null ? `${s.pe.entryPct}%` : "—"}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.pe.triggerPrice)}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.pe.targetPrice)}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtPx(s.pe.stopPrice)}</td>
                      <td className="px-2 py-2">{s.pe.tradable ? "Eligible" : s.pe.skipReason ?? "No trade"}</td>
                    </tr>,
                  ])}
                </tbody>
              </table>
            </div>
          </PremiumCard>

          {debugRows.length > 0 ? (
            <PremiumCard className="!p-0 overflow-hidden">
              <div className="border-b border-[var(--border-subtle)] px-4 py-3">
                <CardTitle title="Debug — Option Data Validation" subtitle="Ref close = end of 10m window · Monitor = session/after-ref candles · Trigger uses post-ref bars only (no look-ahead)" compact />
              </div>
              <div className="max-h-[480px] overflow-auto">
                <table className="min-w-full text-left text-xs">
                  <thead className="sticky top-0 z-10 bg-[var(--surface-muted)]">
                    <tr>
                      {["Date", "Window", "Side", "Ref Close", "Monitor", "Premium", "Trigger", "Trig H", "Trig L", "Target", "Stop", "Trigger Time", "Exit Time", "High Mon", "High Entry", "Low Entry", "Status", "Reason"].map((h) => (
                        <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {debugRows.map((row, i) => (
                      <tr key={i} className={cn("border-t border-[var(--border-subtle)]", row.status === "DATA_ERROR" || row.status === "TOKEN_NOT_FOUND" ? "bg-[var(--danger)]/5" : "")}>
                        <td className="px-2 py-2 whitespace-nowrap">{fmtDate(row.date)}</td>
                        <td className="px-2 py-2">{row.window}</td>
                        <td className="px-2 py-2">{row.side}</td>
                        <td className="px-2 py-2">{row.referenceCandleEnd ?? (row.referenceTime ? row.referenceTime.slice(11, 16) : "—")}</td>
                        <td className="px-2 py-2 tabular-nums text-[10px]" title={`Session ${row.totalSessionCandles ?? "?"} · after ref ${row.monitorCandlesAfterRef ?? row.historicalCandleCount ?? "?"}`}>
                          {row.totalSessionCandles != null ? `${row.totalSessionCandles}/${row.monitorCandlesAfterRef ?? row.historicalCandleCount ?? "?"}` : (row.historicalCandleCount ?? "—")}
                        </td>
                        <td className="px-2 py-2 tabular-nums">{row.premiumClose != null ? fmtPx(row.premiumClose) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.entryTriggerPrice != null ? fmtPx(row.entryTriggerPrice) : row.triggerPrice != null ? fmtPx(row.triggerPrice) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.triggerCandleHigh != null ? fmtPx(row.triggerCandleHigh) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.triggerCandleLow != null ? fmtPx(row.triggerCandleLow) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.targetPrice != null ? fmtPx(row.targetPrice) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.stopPrice != null ? fmtPx(row.stopPrice) : "—"}</td>
                        <td className="px-2 py-2">{row.triggerCandleTime ? row.triggerCandleTime.slice(11, 16) : row.triggerFound ? "Yes" : row.triggerFound === false ? "No" : "—"}</td>
                        <td className="px-2 py-2">{row.exitCandleTime ? row.exitCandleTime.slice(11, 16) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.highestPremiumDuringMonitoring != null ? fmtPx(row.highestPremiumDuringMonitoring) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.highestPremiumAfterEntry != null ? fmtPx(row.highestPremiumAfterEntry) : "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{row.lowestPremiumAfterEntry != null ? fmtPx(row.lowestPremiumAfterEntry) : "—"}</td>
                        <td className="px-2 py-2">{row.status}</td>
                        <td className="max-w-[220px] truncate px-2 py-2" title={row.reason}>{row.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </PremiumCard>
          ) : null}

          <PremiumCard className="!p-4">
            <CardTitle title="Option Premium Chart" subtitle="10m option candles with Base, Trigger, TP, SL and trade markers" />
            <div className="mt-3 flex flex-wrap gap-3">
              <select className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-3 py-1.5 text-sm" value={selectedChartId} onChange={(e) => setSelectedChartId(e.target.value)}>
                {(activeDay?.chartSeries ?? []).map((s) => (
                  <option key={s.id} value={s.id}>{fmtDate(s.date)} · {s.window} · {s.sideLabel} {s.strike}</option>
                ))}
              </select>
            </div>
            <div className="mt-3">
              <BreakoutBacktestChart
                candles={activeChart?.candles ?? []}
                trades={chartTrades}
                levels={activeChart?.levels}
                title={activeChart ? `${activeChart.symbol || activeChart.sideLabel} · Strike ${fmtPx(activeChart.strike)} · Ref SENSEX ${fmtPx(activeChart.referenceClose)}` : undefined}
              />
            </div>
          </PremiumCard>

          <PremiumCard className="!p-0 overflow-hidden">
            <div className="flex items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-4 py-3">
              <CardTitle title="Trade Records" compact />
              <button type="button" onClick={() => exportTradesExcel(tradeRecords)} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--surface-muted)]">
                <Download className="h-3.5 w-3.5" />
                Export Excel (CSV)
              </button>
            </div>
            <div className="max-h-[520px] overflow-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="sticky top-0 z-10 bg-[var(--surface-muted)]">
                  <tr>
                    {["S.No", "Date", "Side", "Window", "Strike", "Entry Time", "Exit Time", "Entry Price", "Exit Price", "Lots", "Size", "Eff Qty", "Exit Reason", "Points", "P&L", "Details"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tradeRecords.length === 0 ? (
                    <tr><td colSpan={16} className="px-3 py-8 text-center text-[var(--text-muted)]">No records</td></tr>
                  ) : (
                    tradeRecords.map((t) => (
                      <tr key={t.id} className="border-t border-[var(--border-subtle)] hover:bg-[var(--surface-muted)]/50">
                        <td className="px-2 py-2">{t.serialNo ?? t.id}</td>
                        <td className="px-2 py-2 whitespace-nowrap">{fmtDate(t.date)}</td>
                        <td className="px-2 py-2">{t.sideLabel ?? t.side}</td>
                        <td className="px-2 py-2">{t.window ?? "—"}</td>
                        <td className="px-2 py-2 tabular-nums">{t.strike ? fmtPx(t.strike) : "—"}</td>
                        <td className="px-2 py-2">{fmtTradeTime(t, "entry")}</td>
                        <td className="px-2 py-2">{fmtTradeTime(t, "exit")}</td>
                        <td className="px-2 py-2 tabular-nums">{fmtTradePrice(t, "entry")}</td>
                        <td className="px-2 py-2 tabular-nums">{fmtTradePrice(t, "exit")}</td>
                        <td className="px-2 py-2">{t.lots ?? "—"}</td>
                        <td className="px-2 py-2">{`${t.sizeMultiplier ?? 1}x`}</td>
                        <td className="px-2 py-2">{t.effectiveQuantity ?? t.lots ?? "—"}</td>
                        <td className="px-2 py-2">{t.exitReason ?? t.status ?? "—"}</td>
                        <td className={cn("px-2 py-2 tabular-nums font-medium", (t.points ?? 0) > 0 ? "text-[var(--success)]" : (t.points ?? 0) < 0 ? "text-[var(--danger)]" : "")}>{fmtPx(t.points)}</td>
                        <td className={cn("px-2 py-2 tabular-nums", (t.pnl ?? 0) > 0 ? "text-[var(--success)]" : (t.pnl ?? 0) < 0 ? "text-[var(--danger)]" : "")}>{fmtPx(t.pnl)}</td>
                        <td className="max-w-[220px] truncate px-2 py-2" title={t.details ?? t.message}>{t.details ?? t.message ?? "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </PremiumCard>
        </>
      ) : null}
    </div>
  );
}
