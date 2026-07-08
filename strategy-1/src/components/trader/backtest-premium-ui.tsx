"use client";

import { motion } from "framer-motion";
import {
  BarChart3,
  Calendar,
  ChevronDown,
  ChevronUp,
  Download,
  Loader2,
  Minus,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Target,
  TrendingDown,
  TrendingUp,
  Zap,
  Layers,
  Repeat,
  Compass,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/components/ui";
import { normalizeEntryLots } from "@/lib/backtest-trend-analysis";

/* ─── Primitives ─── */

export const btInput =
  "h-10 w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-3 text-sm text-[var(--text-primary)] outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-soft)]";

export function BtCard({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay }}
      className={cn(
        "rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] p-4 shadow-[var(--shadow-card)]",
        className,
      )}
    >
      {children}
    </motion.div>
  );
}

export function SettingCard({
  icon: Icon,
  title,
  description,
  children,
  className,
  delay = 0,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <BtCard className={className} delay={delay}>
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
          <p className="text-xs text-[var(--text-muted)]">{description}</p>
        </div>
      </div>
      <div className="space-y-3">{children}</div>
    </BtCard>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-1 text-xs font-medium text-[var(--text-muted)]">
        {label}
        {hint ? <span className="text-[var(--text-muted)]" title={hint}>ⓘ</span> : null}
      </span>
      {children}
    </label>
  );
}

export function EntryLotsSteppers({
  maxEntries,
  entryLots,
  onChange,
}: {
  maxEntries: number;
  entryLots: number[];
  onChange: (lots: number[]) => void;
}) {
  const normalized = normalizeEntryLots(entryLots, maxEntries);
  return (
    <div className="grid grid-cols-2 gap-3">
      {normalized.map((lots, i) => (
        <Field
          key={i}
          label={`Entry ${i + 1} Lots`}
          hint={i === 0 ? "First / core entry (TP2 eligible)" : `Averaging entry #${i + 1}`}
        >
          <NumStepper
            value={lots}
            min={1}
            max={100}
            onChange={(n) => {
              const next = [...normalized];
              next[i] = n;
              onChange(normalizeEntryLots(next, maxEntries));
            }}
          />
        </Field>
      ))}
    </div>
  );
}

export function NumStepper({
  value,
  onChange,
  min = 0,
  max = 99999,
  step = 1,
}: {
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState(String(value));

  useEffect(() => {
    if (!focused) setDraft(String(value));
  }, [value, focused]);

  const dec = () => onChange(Math.max(min, value - step));
  const inc = () => onChange(Math.min(max, value + step));
  return (
    <div className="flex h-10 overflow-hidden rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)]">
      <button type="button" onClick={dec} className="flex w-10 items-center justify-center text-[var(--text-muted)] transition hover:bg-[var(--surface-muted)] hover:text-[var(--accent)]">
        <Minus className="h-3.5 w-3.5" />
      </button>
      <input
        type="number"
        className="min-w-0 flex-1 border-x border-[var(--border-subtle)] bg-transparent text-center font-mono text-sm text-[var(--text-primary)] outline-none"
        value={focused ? draft : String(value)}
        onFocus={() => {
          setFocused(true);
          setDraft(String(value));
        }}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setFocused(false);
          if (draft === "") return;
          const n = parseInt(draft, 10);
          if (Number.isFinite(n)) onChange(Math.min(max, Math.max(min, n)));
        }}
      />
      <button type="button" onClick={inc} className="flex w-10 items-center justify-center text-[var(--text-muted)] transition hover:bg-white/5 hover:text-teal-400">
        <Plus className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function BtToggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-3 py-2.5 text-left transition hover:border-white/15"
    >
      <span className="text-xs font-medium text-[var(--text-secondary)]">{label}</span>
      <span
        className={cn(
          "relative h-5 w-9 rounded-full transition-colors",
          checked ? "bg-[var(--accent)]" : "bg-[var(--surface-muted)]",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </span>
    </button>
  );
}

export function DirectionRadio({
  value,
  onChange,
}: {
  value: "BOTH" | "CALL_ONLY" | "PUT_ONLY";
  onChange: (v: "BOTH" | "CALL_ONLY" | "PUT_ONLY") => void;
}) {
  const opts = [
    { id: "BOTH" as const, label: "Both" },
    { id: "CALL_ONLY" as const, label: "Call Only" },
    { id: "PUT_ONLY" as const, label: "Put Only" },
  ];
  return (
    <div className="space-y-2">
      {opts.map((o) => (
        <label
          key={o.id}
          className={cn(
            "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition",
            value === o.id ? "border-teal-500/50 bg-teal-500/10" : "border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:border-white/15",
          )}
        >
          <input
            type="radio"
            name="trade-direction"
            checked={value === o.id}
            onChange={() => onChange(o.id)}
            className="h-4 w-4 accent-teal-400"
          />
          <span className="text-sm text-[var(--text-secondary)]">{o.label}</span>
        </label>
      ))}
    </div>
  );
}

export function BtHeader({
  onLoadLive,
  onReset,
  onSavePreset,
  onLoadPreset,
  presets,
}: {
  onLoadLive: () => void;
  onReset: () => void;
  onSavePreset: () => void;
  onLoadPreset: (name: string) => void;
  presets: string[];
}) {
  const [presetOpen, setPresetOpen] = useState(false);
  return (
    <div className="flex flex-col gap-4 border-b border-white/[0.06] pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-teal-400/90">Strategy Lab</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-[var(--text-primary)] sm:text-3xl">Backtest</h1>
        <p className="mt-1 max-w-xl text-sm text-[var(--text-muted)]">
          SENSEX Adaptive Trend Averaging — test and validate using historical market data.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onLoadLive} className="bt-btn-secondary">
          <RefreshCw className="h-3.5 w-3.5" /> Load Live Settings
        </button>
        <button type="button" onClick={onReset} className="bt-btn-secondary">
          <RotateCcw className="h-3.5 w-3.5" /> Reset
        </button>
        <button type="button" onClick={onSavePreset} className="bt-btn-secondary">
          <Save className="h-3.5 w-3.5" /> Save Preset
        </button>
        <div className="relative">
          <button type="button" onClick={() => setPresetOpen((o) => !o)} className="bt-btn-secondary">
            Load Preset <ChevronDown className="h-3.5 w-3.5" />
          </button>
          {presetOpen && presets.length > 0 ? (
            <div className="absolute right-0 z-20 mt-1 min-w-[160px] rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] py-1 shadow-xl">
              {presets.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="block w-full px-3 py-2 text-left text-xs text-[var(--text-secondary)] hover:bg-white/5"
                  onClick={() => {
                    onLoadPreset(p);
                    setPresetOpen(false);
                  }}
                >
                  {p}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function RunSection({
  loading,
  progress,
  message,
  onRun,
}: {
  loading: boolean;
  progress: { pct: number; day: number; total: number; elapsed: number };
  message: string | null;
  onRun: () => void;
}) {
  return (
    <BtCard className="!p-5">
      <div className="flex flex-col items-center gap-4">
        <button
          type="button"
          onClick={onRun}
          disabled={loading}
          className={cn(
            "flex h-12 min-w-[220px] items-center justify-center gap-2 rounded-xl text-sm font-bold transition",
            loading
              ? "cursor-wait bg-teal-600/80 text-white"
              : "bg-gradient-to-r from-teal-500 to-emerald-500 text-white shadow-lg shadow-teal-500/25 hover:brightness-110",
          )}
        >
          {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5" />}
          {loading ? "Running Backtest…" : "Run Backtest"}
        </button>
        {loading ? (
          <div className="w-full max-w-md space-y-2">
            <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-muted)]">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-teal-500 to-emerald-400"
                animate={{ width: `${progress.pct}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <div className="flex justify-between text-[11px] text-[var(--text-muted)]">
              <span>Day {progress.day} / {progress.total}</span>
              <span>{progress.elapsed}s elapsed</span>
            </div>
          </div>
        ) : null}
        {message ? (
          <p className={cn("text-center text-xs", message.includes("failed") ? "text-rose-400" : "text-[var(--text-muted)]")}>{message}</p>
        ) : null}
      </div>
    </BtCard>
  );
}

export function SummaryGrid({
  stats,
}: {
  stats: Record<string, string | number> | null;
}) {
  if (!stats) return null;
  const totalPnl = Number(stats.total_pnl ?? 0);
  const up = totalPnl >= 0;
  const tiles = [
    { label: "Net Profit", value: stats.net_profit, tone: up ? "up" : "down", icon: up ? TrendingUp : TrendingDown },
    { label: "Total Trades", value: stats.total_trades, tone: "neutral" },
    { label: "Win Rate", value: `${stats.win_rate}%`, tone: "neutral" },
    { label: "Profit Factor", value: stats.profit_factor, tone: "neutral" },
    { label: "Max Drawdown", value: stats.max_drawdown, tone: "down" },
    { label: "Expectancy", value: stats.expectancy, tone: "neutral" },
    { label: "Avg Win", value: stats.avg_win, tone: "up" },
    { label: "Avg Loss", value: stats.avg_loss, tone: "down" },
    { label: "Largest Win", value: stats.largest_profit, tone: "up" },
    { label: "Largest Loss", value: stats.largest_loss, tone: "down" },
    { label: "Final Capital", value: stats.final_capital, tone: "neutral" },
    { label: "Trade Cycles", value: stats.trade_cycles ?? "—", tone: "neutral" },
    { label: "Closed Exits", value: stats.closed_trades ?? stats.exit_events ?? "—", tone: "neutral" },
    { label: "Re-entry Cycles", value: stats.reentry_cycles ?? "—", tone: "neutral" },
    { label: "Max Averaging", value: stats.max_averaging ?? stats.max_averaging_per_cycle ?? "—", tone: "neutral" },
    { label: "Gross Profit", value: stats.gross_profit, tone: "up" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-xl border border-[var(--border-subtle)] bg-gradient-to-b from-[#121a2e] to-[#0d1322] p-3 transition hover:border-white/12"
        >
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{t.label}</p>
            {t.icon ? <t.icon className={cn("h-3.5 w-3.5", t.tone === "up" ? "text-emerald-400" : t.tone === "down" ? "text-rose-400" : "text-teal-400")} /> : null}
          </div>
          <p
            className={cn(
              "mt-2 font-mono text-xl font-bold tabular-nums",
              t.tone === "up" ? "text-emerald-400" : t.tone === "down" ? "text-rose-400" : "text-[var(--text-primary)]",
            )}
          >
            {t.value ?? "—"}
          </p>
        </div>
      ))}
    </div>
  );
}

export function AnalyticsPanel({
  daySummaries,
  equityCurve,
  drawdownCurve,
  monthly,
  winCount,
  lossCount,
}: {
  daySummaries: { date: string; points: number }[];
  equityCurve: { date: string; equity: number }[];
  drawdownCurve: { date: string; drawdown: number }[];
  monthly: { month: string; points: number }[];
  winCount: number;
  lossCount: number;
}) {
  const Chart = ({
    title,
    data,
    valueKey,
    colorFn,
  }: {
    title: string;
    data: Record<string, unknown>[];
    valueKey: string;
    colorFn: (v: number) => string;
  }) => {
    const vals = data.map((d) => Number(d[valueKey] ?? 0));
    const max = Math.max(...vals.map(Math.abs), 1);
    return (
      <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0d1322] p-3">
        <p className="mb-2 text-xs font-semibold text-[var(--text-muted)]">{title}</p>
        <div className="flex h-28 items-end gap-px">
          {data.map((d, i) => {
            const v = Number(d[valueKey] ?? 0);
            const h = Math.max(4, (Math.abs(v) / max) * 100);
            return (
              <div
                key={i}
                title={`${String(d.date ?? d.month ?? i)}: ${v}`}
                className={cn("flex-1 rounded-t-sm opacity-90 transition hover:opacity-100", colorFn(v))}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <BtCard>
      <div className="mb-3 flex items-center gap-2">
        <BarChart3 className="h-4 w-4 text-teal-400" />
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Analytics</h3>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Chart title="Equity Curve" data={equityCurve} valueKey="equity" colorFn={(v) => (v >= 0 ? "bg-blue-500" : "bg-rose-500")} />
        <Chart title="Drawdown" data={drawdownCurve} valueKey="drawdown" colorFn={() => "bg-amber-500"} />
        <Chart title="Daily P&L" data={daySummaries} valueKey="points" colorFn={(v) => (v >= 0 ? "bg-emerald-500" : "bg-rose-500")} />
        {monthly.length > 1 ? (
          <Chart title="Monthly Performance" data={monthly} valueKey="points" colorFn={(v) => (v >= 0 ? "bg-teal-500" : "bg-rose-500")} />
        ) : null}
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[#0d1322] p-3">
          <p className="mb-2 text-xs font-semibold text-[var(--text-muted)]">Win / Loss Distribution</p>
          <div className="flex h-28 items-end justify-center gap-4">
            <div className="flex flex-col items-center gap-1">
              <div className="w-12 rounded-t bg-emerald-500" style={{ height: `${Math.max(8, (winCount / Math.max(winCount + lossCount, 1)) * 80)}px` }} />
              <span className="text-[10px] text-[var(--text-muted)]">Wins {winCount}</span>
            </div>
            <div className="flex flex-col items-center gap-1">
              <div className="w-12 rounded-t bg-rose-500" style={{ height: `${Math.max(8, (lossCount / Math.max(winCount + lossCount, 1)) * 80)}px` }} />
              <span className="text-[10px] text-[var(--text-muted)]">Loss {lossCount}</span>
            </div>
          </div>
        </div>
      </div>
    </BtCard>
  );
}

export type LogRow = {
  uid: string;
  date: string;
  time: string;
  cycle_id: string;
  side: string;
  action_label: string;
  reason_label: string;
  entry_type: string;
  base_price: number | null;
  trigger_price: number | null;
  index_price: number;
  strike_offset: number | null;
  selected_strike: string;
  average_entry_price: number | null;
  average_level: string | null;
  lots: number;
  total_lots: number | null;
  tp1: number | null;
  tp2_trail: number | null;
  adaptive_high_low: string;
  strike: number;
  entry: number | null;
  exit: number | null;
  stop_loss: number | null;
  adaptive_ref: number | null;
  exit_reason: string;
  trade_pnl: number;
  running_pnl: number;
  action: string;
  strike_detail: string;
};

export function TradeLogTable({
  rows,
  onExportCsv,
  onExportPrint,
}: {
  rows: LogRow[];
  onExportCsv: () => void;
  onExportPrint: () => void;
}) {
  const [search, setSearch] = useState("");
  const [sideFilter, setSideFilter] = useState<"ALL" | "CALL" | "PUT">("ALL");
  const [sortKey, setSortKey] = useState<keyof LogRow>("date");
  const [sortAsc, setSortAsc] = useState(true);

  const filtered = useMemo(() => {
    let list = rows;
    if (sideFilter !== "ALL") list = list.filter((r) => r.side === sideFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((r) =>
        [r.date, r.time, r.side, r.action_label, r.reason_label, r.entry_type, r.exit_reason, r.action, r.cycle_id].some((x) =>
          String(x).toLowerCase().includes(q),
        ),
      );
    }
    list = [...list].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [rows, search, sideFilter, sortKey, sortAsc]);

  const toggleSort = (key: keyof LogRow) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const cols: { key: keyof LogRow; label: string }[] = [
    { key: "date", label: "Date" },
    { key: "time", label: "Time" },
    { key: "cycle_id", label: "Cycle" },
    { key: "action_label", label: "Action" },
    { key: "reason_label", label: "Reason" },
    { key: "side", label: "Side" },
    { key: "base_price", label: "Base" },
    { key: "trigger_price", label: "Trigger" },
    { key: "index_price", label: "Index" },
    { key: "strike_offset", label: "Offset" },
    { key: "selected_strike", label: "Strike" },
    { key: "average_entry_price", label: "Avg Entry" },
    { key: "average_level", label: "Avg Lvl" },
    { key: "lots", label: "Lots" },
    { key: "total_lots", label: "Total" },
    { key: "tp1", label: "TP1" },
    { key: "tp2_trail", label: "TP2 Trail" },
    { key: "adaptive_high_low", label: "Adaptive H/L" },
    { key: "stop_loss", label: "SL" },
    { key: "exit", label: "Exit" },
    { key: "exit_reason", label: "Exit Reason" },
    { key: "trade_pnl", label: "P&L" },
    { key: "running_pnl", label: "Running" },
  ];

  return (
    <BtCard className="!p-0 overflow-hidden">
      <div className="border-b border-white/[0.06] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Trade Log</h3>
            <p className="text-xs text-[var(--text-muted)]">{filtered.length} events · institutional view</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onExportCsv} className="bt-btn-secondary text-[11px]">
              <Download className="h-3 w-3" /> CSV
            </button>
            <button type="button" onClick={onExportPrint} className="bt-btn-secondary text-[11px]">
              PDF / Print
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <div className="relative min-w-[180px] flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              className={cn(btInput, "pl-8")}
              placeholder="Search trades…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {(["ALL", "CALL", "PUT"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSideFilter(s)}
              className={cn(
                "rounded-lg px-3 py-2 text-xs font-medium transition",
                sideFilter === s ? "bg-teal-500/20 text-teal-300" : "bg-white/5 text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full min-w-[2200px] text-left text-[11px]">
          <thead className="sticky top-0 z-10 bg-[var(--surface-elevated)] text-[var(--text-muted)]">
            <tr>
              {cols.map((c) => (
                <th key={c.key} className="whitespace-nowrap px-2 py-2 font-medium">
                  <button type="button" onClick={() => toggleSort(c.key)} className="inline-flex items-center gap-0.5 hover:text-[var(--text-secondary)]">
                    {c.label}
                    {sortKey === c.key ? (sortAsc ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />) : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.uid} className="border-t border-white/[0.04] transition hover:bg-white/[0.02]">
                {cols.map((c) => {
                  const v = row[c.key];
                  const mono = ["trigger_price", "index_price", "base_price", "average_entry_price", "tp1", "tp2_trail", "stop_loss", "exit", "trade_pnl", "running_pnl"].includes(c.key);
                  const tone =
                    c.key === "trade_pnl" && typeof v === "number"
                      ? v >= 0 ? "text-emerald-400" : "text-rose-400"
                      : c.key === "side"
                        ? row.side === "CALL" ? "text-emerald-400" : "text-rose-400"
                        : c.key === "action_label"
                          ? "text-teal-300 font-medium"
                          : "text-[var(--text-secondary)]";
                  return (
                    <td key={c.key} className={cn("whitespace-nowrap px-2 py-1.5", mono && "font-mono", tone)}>
                      {v == null || v === "" ? "" : String(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
            {!filtered.length ? (
              <tr><td colSpan={16} className="px-3 py-8 text-center text-[var(--text-muted)]">No events match your filters.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </BtCard>
  );
}

export const settingIcons = { Calendar, Zap, Layers, Target, Repeat, Compass };
