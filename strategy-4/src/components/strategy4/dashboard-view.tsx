"use client";

import { Play, Square } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useEngineStatus } from "@/components/trader/app-shell";
import { AngelTokenRefreshBanner } from "@/components/trader/angel-token-refresh";
import { ConfirmModal } from "@/components/trader/ui/confirm-modal";
import { CardTitle, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { useStrategy4Dashboard } from "@/hooks/use-strategy4-dashboard";
import { detectMcxQuotesTokenExpiry } from "@/lib/angel-session";
import { setAlgoRunning, setTradingMode } from "@/lib/strategy4/api";
import type { DashboardSnapshot, MarketQuote, TradingMode } from "@/lib/strategy4/types";
import { cn } from "@/components/ui";

function fmtPx(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v) || v === 0) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPnl(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

function fmtTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(d);
}

function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${fmtDate(iso)} ${fmtTime(iso)}`;
}

function durationLabel(entry: string | null | undefined, exit: string | null | undefined) {
  if (!entry || !exit) return "—";
  const a = new Date(entry).getTime();
  const b = new Date(exit).getTime();
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return "—";
  const mins = Math.round((b - a) / 60000);
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

function tradeLabel(leg: string, reverse?: boolean) {
  const u = (leg || "").toUpperCase();
  if (u === "REVERSE" || reverse) return "Reverse";
  if (u === "MAIN" || u === "INITIAL") return "Initial";
  return leg || "—";
}

function exitReasonLabel(reason: string | null | undefined) {
  const r = (reason || "").toUpperCase();
  if (r.includes("TP")) return "TP";
  if (r.includes("SL")) return "SL";
  return reason || "—";
}

function phaseLabel(phase: string | undefined) {
  switch ((phase || "").toUpperCase()) {
    case "IDLE":
      return "Idle";
    case "WAIT_REF":
      return "Waiting reference";
    case "WAIT_BREAKOUT":
      return "Waiting breakout";
    case "IN_TRADE":
      return "In trade";
    case "REVERSE_TRADE":
      return "Reverse trade";
    case "DONE":
      return "Done for today";
    default:
      return phase || "—";
  }
}

function DataTable({
  title,
  headers,
  rows,
  empty,
  action,
}: {
  title: string;
  headers: string[];
  rows: (string | number)[][];
  empty: string;
  action?: ReactNode;
}) {
  return (
    <PremiumCard className="!p-0 overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-4 py-3">
        <CardTitle title={title} compact />
        {action}
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
              {headers.map((h) => (
                <th key={h} className="whitespace-nowrap px-3 py-2 font-medium text-[var(--text-secondary)]">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={headers.length} className="px-3 py-6 text-center text-[var(--text-muted)]">
                  {empty}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr key={i} className="border-b border-[var(--border-subtle)] last:border-0">
                  {row.map((cell, j) => (
                    <td key={j} className="max-w-[28rem] whitespace-pre-wrap break-words px-3 py-2 text-[var(--text-primary)]">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </PremiumCard>
  );
}

function StatusCard({
  data,
  quote,
}: {
  data: DashboardSnapshot | null | undefined;
  quote: MarketQuote | undefined;
}) {
  const phase = data?.phase || "";
  const cmp = data?.current_market_price ?? quote?.price ?? 0;
  const isLive = Boolean(quote?.market_open && quote?.source === "live");

  return (
    <PremiumCard className="!p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle
            title={(data?.market || "Market").replace(/_/g, " ")}
            subtitle={data?.active_symbol || quote?.tradingsymbol || "—"}
          />
        </div>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
              isLive ? "bg-[var(--success-soft)] text-[var(--success)]" : "bg-[var(--warning-soft)] text-[var(--warning)]",
            )}
          >
            {isLive ? "LTP · Live" : "LTP · Last"}
          </span>
          <span className="rounded-full bg-[var(--surface-muted)] px-3 py-1 text-[11px] font-semibold">
            {phaseLabel(phase)}
          </span>
        </div>
      </div>

      <p className="mt-3 text-4xl font-semibold tabular-nums text-[var(--text-primary)]">{fmtPx(cmp)}</p>

      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-[10px] uppercase text-[var(--text-muted)]">Session</dt>
          <dd className="text-sm font-medium">
            {data?.session_start || "—"} – {data?.session_end || "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase text-[var(--text-muted)]">Ref / Buy / Sell</dt>
          <dd className="text-sm font-medium tabular-nums">
            {fmtPx(data?.reference_price)} / {fmtPx(data?.buy_trigger)} / {fmtPx(data?.sell_trigger)}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase text-[var(--text-muted)]">Lots · Dist · TP/SL</dt>
          <dd className="text-sm font-medium tabular-nums">
            {data?.lots ?? "—"} · ±{data?.breakout_distance ?? "—"} · {data?.take_profit_pts ?? "—"}/{data?.stop_loss_pts ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase text-[var(--text-muted)]">P&amp;L · Trades</dt>
          <dd className="text-sm font-medium tabular-nums">
            {fmtPnl(data?.realized_pnl)} · {data?.trade_count ?? 0}
          </dd>
        </div>
      </dl>

      {(phase || "").toUpperCase() === "IN_TRADE" || (phase || "").toUpperCase() === "REVERSE_TRADE" ? (
        <p className="mt-3 text-sm tabular-nums text-[var(--text-secondary)]">
          Open {data?.is_reverse ? "Reverse" : "Initial"} {data?.active_side || "—"} · Entry {fmtPx(data?.entry_price)} · TP{" "}
          {fmtPx(data?.tp_price)} · SL {fmtPx(data?.sl_price)}
        </p>
      ) : (
        <p className="mt-3 text-sm text-[var(--text-secondary)]">{data?.status_message || data?.next_action_level || "—"}</p>
      )}
    </PremiumCard>
  );
}

export function Strategy4DashboardView() {
  const { data, loading, error, refresh, serverOnline, clearCompleted, clearLogs } = useStrategy4Dashboard();
  const { setAlgoRunningLocal } = useEngineStatus();
  const [busy, setBusy] = useState(false);
  const [clearLogsModal, setClearLogsModal] = useState(false);
  const [clearHistoryModal, setClearHistoryModal] = useState(false);

  const quotes = serverOnline ? (data?.quotes ?? []) : [];
  const activeTrades = serverOnline ? (data?.active_trades ?? []) : [];
  const completedTrades = serverOnline ? (data?.completed_trades ?? []) : [];
  const logs = serverOnline ? (data?.logs ?? []) : [];
  const showAngelTokenRefresh = serverOnline && detectMcxQuotesTokenExpiry(quotes);
  const selectedMarket = (data?.market || String(data?.config?.market || "")).toUpperCase();
  const activeQuote = useMemo(
    () => quotes.find((q) => q.key.toUpperCase() === selectedMarket) ?? quotes[0],
    [quotes, selectedMarket],
  );

  const dayPnlById = useMemo(() => {
    const sorted = [...completedTrades].sort((a, b) => {
      const ta = new Date(a.exit_time || a.entry_time || 0).getTime();
      const tb = new Date(b.exit_time || b.entry_time || 0).getTime();
      return ta - tb;
    });
    const map = new Map<number, number>();
    let running = 0;
    for (const t of sorted) {
      running += Number(t.pnl || 0);
      map.set(t.id, running);
    }
    return map;
  }, [completedTrades]);

  async function toggleAlgo(enable: boolean) {
    setBusy(true);
    try {
      await setAlgoRunning(enable);
      setAlgoRunningLocal(enable);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function changeMode(mode: TradingMode) {
    setBusy(true);
    try {
      await setTradingMode(mode);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) {
    return <p className="text-sm text-[var(--text-muted)]">Loading dashboard…</p>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-10">
      <PageHeader title="Dashboard" subtitle="Strategy 4 — MCX breakout + reverse" />

      {error ? (
        <p className="rounded-xl border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-4 py-3 text-sm text-[var(--danger)]">{error}</p>
      ) : null}

      {!serverOnline ? (
        <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Server offline — trades and logs are hidden until the server is back.
        </p>
      ) : null}

      <AngelTokenRefreshBanner show={showAngelTokenRefresh} />

      <PremiumCard className="!p-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={busy || data?.algo_running}
            onClick={() => void toggleAlgo(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--success)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Enable Algo
          </button>
          <button
            type="button"
            disabled={busy || !data?.algo_running}
            onClick={() => void toggleAlgo(false)}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--danger)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <Square className="h-4 w-4" />
            Disable Algo
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Mode</span>
            {(["PAPER", "LIVE"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                disabled={busy}
                onClick={() => void changeMode(mode)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-medium",
                  data?.trading_mode === mode
                    ? "bg-[var(--accent)] text-white"
                    : "border border-[var(--border-subtle)] text-[var(--text-secondary)]",
                )}
              >
                {mode === "PAPER" ? "Paper" : "Live"}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Algo: {data?.algo_running ? "Running" : "Stopped"} · Mode: {data?.trading_mode ?? "PAPER"}
        </p>
      </PremiumCard>

      <StatusCard data={data} quote={activeQuote} />

      <DataTable
        title="Active Trades"
        headers={["Time", "Side", "Leg", "Lots", "Entry", "Mark", "P&L", "Mode"]}
        rows={activeTrades.map((t) => [
          fmtDateTime(t.entry_time),
          t.side || "—",
          tradeLabel(t.leg_id),
          t.lots,
          fmtPx(t.entry_price),
          fmtPx(t.current_price),
          fmtPnl(t.pnl),
          t.trading_mode,
        ])}
        empty={serverOnline ? "No open trades" : "Server offline"}
      />

      <DataTable
        title="Completed Trades"
        headers={[
          "Date",
          "Trade",
          "Direction",
          "Entry Time",
          "Entry",
          "TP",
          "SL",
          "Exit Time",
          "Exit",
          "Exit Reason",
          "Duration",
          "Lots",
          "Trade P&L",
          "Day P&L",
        ]}
        rows={completedTrades.map((t) => [
          fmtDate(t.entry_time || t.exit_time),
          tradeLabel(t.leg_id),
          t.side || "—",
          fmtTime(t.entry_time),
          fmtPx(t.entry_price),
          fmtPx(t.tp),
          fmtPx(t.sl),
          fmtTime(t.exit_time),
          fmtPx(t.exit_price),
          exitReasonLabel(t.exit_reason),
          durationLabel(t.entry_time, t.exit_time),
          t.lots ?? "—",
          fmtPnl(t.pnl),
          fmtPnl(dayPnlById.get(t.id)),
        ])}
        empty={serverOnline ? "No completed trades" : "Server offline"}
        action={
          serverOnline ? (
            <button
              type="button"
              disabled={completedTrades.length === 0}
              onClick={() => setClearHistoryModal(true)}
              className="rounded-lg border border-[var(--border-subtle)] px-3 py-1 text-[11px] font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] disabled:opacity-50"
            >
              Clear History
            </button>
          ) : null
        }
      />

      <DataTable
        title="Logs"
        headers={["Time", "Action", "Leg", "Qty", "P&L", "Message"]}
        rows={logs.map((l) => [
          fmtDateTime(l.created_at),
          l.action,
          l.leg,
          l.quantity ?? "—",
          l.pnl != null ? fmtPnl(l.pnl) : "—",
          l.message ?? "—",
        ])}
        empty={serverOnline ? "No logs yet" : "Server offline"}
        action={
          serverOnline ? (
            <button
              type="button"
              disabled={logs.length === 0}
              onClick={() => setClearLogsModal(true)}
              className="rounded-lg border border-[var(--border-subtle)] px-3 py-1 text-[11px] font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] disabled:opacity-50"
            >
              Clear logs
            </button>
          ) : null
        }
      />

      <ConfirmModal
        open={clearLogsModal}
        title="Clear all logs?"
        message="This removes all trading log messages from your account. Open trades are not affected."
        confirmLabel="Clear logs"
        danger
        onCancel={() => setClearLogsModal(false)}
        onConfirm={() => {
          setClearLogsModal(false);
          void clearLogs();
        }}
      />

      <ConfirmModal
        open={clearHistoryModal}
        title="Clear completed trades?"
        message="This permanently deletes all completed trade history. Open positions are not affected."
        confirmLabel="Clear History"
        danger
        onCancel={() => setClearHistoryModal(false)}
        onConfirm={() => {
          setClearHistoryModal(false);
          void clearCompleted();
        }}
      />
    </div>
  );
}
