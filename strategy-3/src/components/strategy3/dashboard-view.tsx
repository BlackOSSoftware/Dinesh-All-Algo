"use client";

import { Play, Square } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useEngineStatus } from "@/components/trader/app-shell";
import { ConfirmModal } from "@/components/trader/ui/confirm-modal";
import { CardTitle, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { useStrategy3Dashboard } from "@/hooks/use-strategy3-dashboard";
import { setAlgoRunning, setTradingMode } from "@/lib/strategy3/api";
import type { TradingMode } from "@/lib/strategy3/types";
import { cn } from "@/components/ui";

function fmtPx(n: number) {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtTime(iso?: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", { hour12: true });
  } catch {
    return iso;
  }
}

export function Strategy3DashboardView() {
  const { snap, loading, error, serverOnline, clearCompleted, clearLogs } = useStrategy3Dashboard();
  const { algoRunning, setAlgoRunningLocal } = useEngineStatus();
  const [mode, setMode] = useState<TradingMode>("PAPER");
  const [busy, setBusy] = useState(false);
  const [clearLogsModal, setClearLogsModal] = useState(false);
  const [clearHistoryModal, setClearHistoryModal] = useState(false);

  useEffect(() => {
    if (snap) {
      setAlgoRunningLocal(snap.algo_running);
      setMode(snap.trading_mode);
    }
  }, [snap, setAlgoRunningLocal]);

  async function toggleAlgo(next: boolean) {
    setBusy(true);
    try {
      await setAlgoRunning(next);
      setAlgoRunningLocal(next);
    } finally {
      setBusy(false);
    }
  }

  async function changeMode(next: TradingMode) {
    setBusy(true);
    try {
      await setTradingMode(next);
      setMode(next);
    } finally {
      setBusy(false);
    }
  }

  const sensex = snap?.sensex_price ?? 0;
  const windows = snap?.windows ?? [];
  const activeTrades = serverOnline ? (snap?.active_trades ?? []) : [];
  const completedTrades = serverOnline ? (snap?.completed_trades ?? []) : [];
  const logs = serverOnline ? (snap?.logs ?? []) : [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 pb-10">
      <PageHeader title="Dashboard" subtitle="SENSEX Expiry Day ITM Breakout" />

      {error ? (
        <p className="rounded-xl border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </p>
      ) : null}

      {!serverOnline ? (
        <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Server offline — active trades, completed trades, and logs are hidden until the server is back.
        </p>
      ) : null}

      <PremiumCard className="!p-4">
        <div className="flex items-center justify-between gap-2">
          <CardTitle title="SENSEX Live" compact />
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              snap?.sensex_market_open
                ? "bg-[var(--success-soft)] text-[var(--success)]"
                : "bg-[var(--surface-muted)] text-[var(--text-muted)]",
            )}
          >
            {snap?.sensex_market_open ? "Live" : "Closed / Last"}
          </span>
        </div>
        <p className="mt-2 text-4xl font-semibold tabular-nums">
          {loading && !snap ? "…" : sensex > 0 ? fmtPx(sensex) : "—"}
        </p>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          Source: {snap?.sensex_source ?? "—"}
          {snap?.sensex_error ? ` · ${snap.sensex_error}` : ""}
        </p>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={busy || algoRunning}
            onClick={() => void toggleAlgo(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--success)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Enable Algo
          </button>
          <button
            type="button"
            disabled={busy || !algoRunning}
            onClick={() => void toggleAlgo(false)}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--danger)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <Square className="h-4 w-4" />
            Disable Algo
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Mode</span>
            {(["PAPER", "LIVE"] as const).map((m) => (
              <button
                key={m}
                type="button"
                disabled={busy}
                onClick={() => void changeMode(m)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-medium",
                  mode === m
                    ? "bg-[var(--accent)] text-white"
                    : "border border-[var(--border-subtle)] text-[var(--text-secondary)]",
                )}
              >
                {m === "PAPER" ? "Paper" : "Live"}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Algo: {algoRunning ? "Running" : "Stopped"} · Realized {fmtPx(snap?.realized_pnl ?? 0)} · Unrealized{" "}
          {fmtPx(snap?.unrealized_pnl ?? 0)}
        </p>
      </PremiumCard>

      <PremiumCard className="!p-0 overflow-hidden">
        <div className="border-b border-[var(--border-subtle)] px-4 py-3">
          <CardTitle title="Trade Windows" subtitle="ITM CE / PE strikes per window" compact />
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                <th className="px-3 py-2">Window</th>
                <th className="px-3 py-2">Ref Close</th>
                <th className="px-3 py-2">CE Strike</th>
                <th className="px-3 py-2">PE Strike</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {windows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-[var(--text-muted)]">
                    Configure settings to preview windows
                  </td>
                </tr>
              ) : (
                windows.map((w) => (
                  <tr key={w.index} className="border-b border-[var(--border-subtle)]">
                    <td className="px-3 py-2 font-medium">{w.start_hhmm}</td>
                    <td className="px-3 py-2 tabular-nums">
                      {w.reference_close ? fmtPx(w.reference_close) : "—"}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{w.ce?.strike ? fmtPx(w.ce.strike) : "—"}</td>
                    <td className="px-3 py-2 tabular-nums">{w.pe?.strike ? fmtPx(w.pe.strike) : "—"}</td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">{w.ce?.skip_reason ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </PremiumCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <DataTable
          title="Active Trades"
          headers={["Leg", "Strike", "Entry", "Mark", "P&L", "Mode"]}
          rows={activeTrades.map((t) => [
            t.side,
            fmtPx(t.strike),
            fmtPx(t.entry_price),
            fmtPx(t.current_price),
            fmtPx(t.pnl),
            t.trading_mode,
          ])}
          empty={serverOnline ? "No open trades" : "Server offline"}
        />
        <DataTable
          title="Completed Trades"
          headers={["Leg", "Entry", "Exit", "P&L", "Reason"]}
          rows={completedTrades.map((t) => [
            t.side,
            fmtPx(t.entry_price),
            t.exit_price != null ? fmtPx(t.exit_price) : "—",
            t.pnl != null ? fmtPx(t.pnl) : "—",
            t.exit_reason ?? "—",
          ])}
          empty={serverOnline ? "No completed trades" : "Server offline — trade history is hidden"}
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
      </div>

      <DataTable
        title="Logs"
        headers={["Time", "Action", "Leg", "Message"]}
        rows={logs.map((l) => [fmtTime(l.created_at), l.action, l.leg, l.message ?? "—"])}
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

function DataTable({
  title,
  headers,
  rows,
  empty,
  action,
}: {
  title: string;
  headers: string[];
  rows: string[][];
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
                <th key={h} className="px-3 py-2 font-medium text-[var(--text-secondary)]">
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
                <tr key={i} className="border-b border-[var(--border-subtle)]">
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-2 tabular-nums">
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
