"use client";

import { Download, Loader2, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { GridBacktestChart } from "@/components/strategy2/grid-backtest-chart";
import { CardTitle, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { runGridBacktest } from "@/lib/strategy2/api";
import {
  DEFAULT_BACKTEST_CONFIG,
  loadBacktestConfig,
  saveBacktestConfig,
  type GridBacktestResult,
  type GridBacktestTrade,
  type MarketKey,
  type Strategy2Config,
} from "@/lib/strategy2/types";
import { cn } from "@/components/ui";

const MARKETS: { value: MarketKey; label: string }[] = [
  { value: "CRUDE_OIL", label: "Crude Oil" },
  { value: "NATURAL_GAS", label: "Natural Gas" },
  { value: "SILVER_MICRO", label: "Silver Micro" },
];

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

export function Strategy2BacktestView() {
  const [cfg, setCfg] = useState<Strategy2Config>(DEFAULT_BACKTEST_CONFIG);
  const [fromDate, setFromDate] = useState(daysAgoIso(4));
  const [toDate, setToDate] = useState(todayIso());
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<GridBacktestResult | null>(null);
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
  const trades = result?.trades ?? [];
  const daySummaries = result?.daySummaries ?? [];
  const gridLevels = result?.gridLevels ?? [];
  const chartCandles = result?.candles ?? [];
  const chartTrades = result?.chartTrades ?? [];

  const subtitle = useMemo(() => {
    if (!result) return "MCX grid backtest — same algo as live trading";
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
    if (cfg.referencePrice <= 0 || cfg.gridGap <= 0 || cfg.initialLots <= 0) {
      setMessage("Reference price, grid gap, and initial lots must be greater than zero.");
      return;
    }

    setLoading(true);
    setMessage("Fetching candles and running grid simulation…");
    setResult(null);
    const t0 = performance.now();

    try {
      const data = await runGridBacktest({
        fromDate,
        toDate,
        ...cfg,
      });
      setResult(data);
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
      ["MCX Grid Backtest Report"],
      ["From Date", fmtDate(fromDate)],
      ["To Date", fmtDate(toDate)],
      ["Market", cfg.market],
      ["Instrument", result.instrument],
      ["Reference Price", cfg.referencePrice],
      ["Grid Gap", cfg.gridGap],
      ["Initial Lots", cfg.initialLots],
      ["Lots Per Grid", cfg.lotsPerGrid],
      ["Levels Above", cfg.gridLevelsAbove],
      ["Levels Below", cfg.gridLevelsBelow],
      ["Session", `${cfg.startTime} – ${cfg.endTime}`],
      [],
      ["Summary"],
      ["Total Trades", result.summary.totalTrades],
      ["Total P&L", result.summary.totalPnl],
      ["Final Position Lots", result.summary.finalPositionLots],
      ["Max Lots", result.summary.maxLots],
      ["Win Days", result.summary.winDays],
      ["Loss Days", result.summary.lossDays],
      [],
      ["Day Summary"],
      ["Date", "Trades", "Day P&L", "End Position", "Candles"],
      ...daySummaries.map((d) => [fmtDate(d.date), d.trades, d.pnl, d.endPositionLots, d.candles]),
      [],
      ["Grid Levels"],
      ["Level", "Price", "Action"],
      ...gridLevels.map((g) => [g.level, g.price, g.action]),
      [],
      ["Trade Record"],
      ["#", "Date", "Time", "Action", "Level", "Side", "Lots", "Grid Price", "Fill Price", "Position After", "Realized P&L", "Message"],
      ...trades.map((t: GridBacktestTrade) => [
        t.id,
        fmtDate(t.date),
        t.time,
        t.action,
        t.level,
        t.side,
        t.lots,
        t.levelPrice ?? t.gridEntryPrice ?? t.gridExitPrice ?? "",
        t.fillPrice ?? t.entryPrice ?? t.exitPrice ?? t.price,
        t.positionAfter,
        t.realizedPnl,
        t.message,
      ]),
    ];

    const csv = rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "application/vnd.ms-excel;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mcx-grid-backtest-${fromDate}_to_${toDate}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-10">
      <PageHeader title="Backtest" subtitle={subtitle} />

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
            label="Start Time"
            type="time"
            value={cfg.startTime}
            onChange={(v) => setCfg((c) => ({ ...c, startTime: v }))}
          />
          <FloatingField
            id="bt-end"
            label="End Time (MCX Market)"
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
        <CardTitle title="Backtest Parameters" subtitle="Independent from live Strategy Settings — changes here do not affect the algo." />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block space-y-2 sm:col-span-2 lg:col-span-4">
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
          <FloatingField
            id="bt-ref"
            label="Reference Price"
            type="number"
            placeholder=""
            value={numInput(cfg.referencePrice)}
            onChange={(v) => setCfg((c) => ({ ...c, referencePrice: parseNum(v) }))}
          />
          <FloatingField
            id="bt-init"
            label="Initial Lots"
            type="number"
            placeholder=""
            value={numInput(cfg.initialLots)}
            onChange={(v) => setCfg((c) => ({ ...c, initialLots: parseNum(v) }))}
          />
          <FloatingField
            id="bt-gap"
            label="Grid Gap (Points)"
            type="number"
            placeholder=""
            value={numInput(cfg.gridGap)}
            onChange={(v) => setCfg((c) => ({ ...c, gridGap: parseNum(v) }))}
          />
          <FloatingField
            id="bt-lots"
            label="Lots Per Grid"
            type="number"
            placeholder=""
            value={numInput(cfg.lotsPerGrid)}
            onChange={(v) => setCfg((c) => ({ ...c, lotsPerGrid: parseNum(v) }))}
          />
          <FloatingField
            id="bt-above"
            label="Grid Levels Above"
            type="number"
            placeholder=""
            value={numInput(cfg.gridLevelsAbove)}
            onChange={(v) => setCfg((c) => ({ ...c, gridLevelsAbove: parseNum(v) }))}
          />
          <FloatingField
            id="bt-below"
            label="Grid Levels Below"
            type="number"
            placeholder=""
            value={numInput(cfg.gridLevelsBelow)}
            onChange={(v) => setCfg((c) => ({ ...c, gridLevelsBelow: parseNum(v) }))}
          />
          <div className="sm:col-span-2">
            <button
              type="button"
              onClick={() => setCfg((c) => ({ ...c, invertGrid: !c.invertGrid }))}
              className={`w-full rounded-xl border px-4 py-3 text-left text-sm transition ${
                cfg.invertGrid
                  ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--border-subtle)] bg-[var(--surface-muted)] text-[var(--text-primary)]"
              }`}
            >
              {cfg.invertGrid ? "Opposite Grid — ON" : "Opposite Grid — OFF"}
            </button>
          </div>
        </div>
      </PremiumCard>

      {summary ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[
            { label: "Total P&L", value: fmtPx(summary.totalPnl), tone: summary.totalPnl >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]" },
            { label: "Total Trades", value: String(summary.totalTrades) },
            { label: "Final Position", value: `${summary.finalPositionLots} lots` },
            { label: "Max Lots", value: String(summary.maxLots) },
            { label: "Win / Loss Days", value: `${summary.winDays} / ${summary.lossDays}` },
          ].map((card) => (
            <PremiumCard key={card.label} className="!p-4">
              <p className="text-xs text-[var(--text-muted)]">{card.label}</p>
              <p className={cn("mt-1 text-xl font-semibold", card.tone ?? "text-[var(--text-primary)]")}>{card.value}</p>
            </PremiumCard>
          ))}
        </div>
      ) : null}

      <PremiumCard className="!p-4">
        <CardTitle
          title="Price Chart & Trades"
          subtitle={result?.chartSubtitle || "Candles with buy/sell markers at each grid action"}
        />
        <GridBacktestChart
          candles={chartCandles}
          trades={chartTrades}
          gridLevels={gridLevels}
          referencePrice={result?.referencePrice}
        />
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Day-wise Analysis" subtitle={daySummaries.length ? `${daySummaries.length} trading day(s)` : "Run backtest to see daily breakdown"} />
        <ScrollTable>
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-[var(--text-muted)]">
              <tr className="border-b border-[var(--border-subtle)]">
                <Th>Date</Th>
                <Th>Trades</Th>
                <Th>Day P&L</Th>
                <Th>End Position</Th>
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
                  <td className="px-3 py-2">{r.endPositionLots} lots</td>
                  <td className="px-3 py-2">{r.candles}</td>
                </tr>
              ))}
              {!daySummaries.length ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-[var(--text-muted)]">
                    No data yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </ScrollTable>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle
          title="Trade Record"
          subtitle={
            trades.length
              ? `${trades.length} grid action(s) · Grid Price = level trigger · Fill Price = candle execution`
              : "All buy/add/re-enter/exit events"
          }
          action={
            <button
              type="button"
              disabled={!trades.length}
              onClick={exportExcel}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-3 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--accent)] disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              Export Excel
            </button>
          }
        />
        <ScrollTable maxH="max-h-[480px]">
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className="text-xs text-[var(--text-muted)]">
              <tr className="border-b border-[var(--border-subtle)]">
                <Th>#</Th>
                <Th>Date</Th>
                <Th>Time</Th>
                <Th>Action</Th>
                <Th>Level</Th>
                <Th>Side</Th>
                <Th>Lots</Th>
                <Th>Grid Price</Th>
                <Th>Fill Price</Th>
                <Th>Position</Th>
                <Th>Realized P&L</Th>
                <Th>Message</Th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const gridPx = t.levelPrice || t.gridEntryPrice || t.gridExitPrice || 0;
                const fillPx = t.fillPrice ?? t.entryPrice ?? t.exitPrice ?? t.price;
                return (
                <tr key={t.id} className="border-b border-[var(--border-subtle)] text-[var(--text-secondary)]">
                  <td className="px-3 py-2">{t.id}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{fmtDate(t.date)}</td>
                  <td className="px-3 py-2 font-mono">{shortTime(t.time)}</td>
                  <td className="px-3 py-2">{t.action.replaceAll("_", " ")}</td>
                  <td className="px-3 py-2 font-mono">{t.level}</td>
                  <td className={cn("px-3 py-2 font-semibold", t.side === "BUY" ? "text-[var(--success)]" : "text-[var(--danger)]")}>{t.side}</td>
                  <td className="px-3 py-2">{t.lots}</td>
                  <td className="px-3 py-2 font-mono font-medium text-[var(--accent)]">{fmtPx(gridPx)}</td>
                  <td className="px-3 py-2 font-mono">{fmtPx(fillPx)}</td>
                  <td className="px-3 py-2">{t.positionAfter}</td>
                  <td className="px-3 py-2 font-mono">{fmtPx(t.realizedPnl)}</td>
                  <td className="px-3 py-2 text-xs">{t.message}</td>
                </tr>
              );
              })}
              {!trades.length ? (
                <tr>
                  <td colSpan={12} className="px-3 py-6 text-center text-[var(--text-muted)]">
                    No trades yet.
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

function shortTime(s: string) {
  return s.replace("T", " ").slice(11, 16) || s.slice(0, 5);
}
