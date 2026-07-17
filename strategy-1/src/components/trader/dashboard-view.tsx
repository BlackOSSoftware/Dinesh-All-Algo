"use client";

import { AlertTriangle, RefreshCw, TrendingUp } from "lucide-react";
import { useState } from "react";

import { useEngineStatus } from "@/components/trader/app-shell";
import { CalculatedTradesTable } from "@/components/trader/strategy-terminal/calculated-trades-table";
import { useTradingDashboard } from "@/components/trader/trading-dashboard-context";
import { CardTitle, MetricBadge, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { ConfirmModal } from "@/components/trader/ui/confirm-modal";
import { useStrategyTerminal } from "@/hooks/use-strategy-terminal";
import { fmtLevel } from "@/lib/strategy-reference";
import { cn } from "@/components/ui";

const ACTIVE_COLS = [
  "Leg",
  "Side",
  "Status",
  "Entry Time",
  "Symbol",
  "Index Entry",
  "Entry Price",
  "Lots",
  "Qty",
  "TP1",
  "TP2 Trail",
  "Stop Loss",
  "Mark",
  "PnL",
  "Order ID",
  "",
] as const;

const COMPLETED_COLS = [
  "Entry Time",
  "Exit Time",
  "Leg",
  "Side",
  "Symbol",
  "Entry Price",
  "Exit Price",
  "Lots",
  "PnL",
  "Mode",
  "Exit Reason",
] as const;

const LOG_COLS = ["Time", "Mode", "Action", "Leg", "Symbol", "Qty", "P&L", "Status", "Message"] as const;

function fmtExitReason(reason: string | null | undefined): string {
  if (!reason) return "—";
  const map: Record<string, string> = {
    AUTO_EXIT: "Session End (EOD)",
    END_TIME: "Session End",
    CALL_SL_HIT: "Call Stop Loss",
    PUT_SL_HIT: "Put Stop Loss",
    TP_HIT: "Take Profit",
    SENSEX_BASE_SL: "Base Stop Loss",
    MANUAL_CLOSE: "Manual Close",
  };
  return map[reason.toUpperCase()] ?? reason.replace(/_/g, " ");
}

function StatusTile({
  label,
  value,
  tone = "neutral",
  large,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn" | "bad";
  large?: boolean;
}) {
  const toneMap = {
    neutral: "neutral" as const,
    ok: "success" as const,
    warn: "warning" as const,
    bad: "danger" as const,
  };
  return <MetricBadge label={label} value={value} tone={toneMap[tone]} size={large ? "lg" : "md"} />;
}

function statusClass(status: string): string {
  const s = status.toUpperCase();
  if (s === "OPEN" || s === "FILLED") return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400";
  if (s === "PENDING_FILL") return "bg-amber-500/15 text-amber-700 dark:text-amber-400";
  if (s === "REJECTED" || s.includes("ERROR")) return "bg-rose-500/15 text-rose-700 dark:text-rose-400";
  return "bg-[var(--surface-elevated)] text-[var(--text-muted)]";
}

export function DashboardView() {
  const t = useStrategyTerminal();
  const d = t.d;
  const { engineOn, engineCheckPending } = useEngineStatus();
  const [clearModal, setClearModal] = useState(false);
  const [clearLogsModal, setClearLogsModal] = useState(false);
  const [closeAllModal, setCloseAllModal] = useState(false);
  const [closingAll, setClosingAll] = useState(false);

  const livePx = t.liveIndex;
  const basePrice = t.basePrice;
  const sensexStale = d.angelTokenExpired || d.angel?.quote_source === "disk";
  const sessionDiff = livePx != null && basePrice != null ? livePx - basePrice : null;
  const serverOnline = engineOn && d.serverOnline;

  const directionLabel =
    d.activeTrades.some((tr) => /call|ce/i.test(tr.side)) && d.activeTrades.some((tr) => /put|pe/i.test(tr.side))
      ? "Call + Put"
      : d.activeTrades.some((tr) => /call|ce/i.test(tr.side))
        ? "Call"
        : d.activeTrades.some((tr) => /put|pe/i.test(tr.side))
          ? "Put"
          : "Flat";

  const completedRows = serverOnline ? d.completedTrades : [];
  const logRows = serverOnline ? d.tradingLogs : [];

  // Today's PnL (IST): realized from trades closed today + unrealized from open trades.
  const istDay = (iso: string | null | undefined) => {
    if (!iso) return "";
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return "";
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(dt);
  };
  const todayIst = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const todayRealized = completedRows
    .filter((c) => istDay(c.exit_time) === todayIst)
    .reduce((sum, c) => sum + (c.pnl ?? 0), 0);
  const todayPnl = todayRealized + (serverOnline ? d.activeTrades : []).reduce((sum, a) => sum + (a.pnl || 0), 0);

  async function confirmCloseAll() {
    setClosingAll(true);
    try {
      await d.closeAllTrades();
    } finally {
      setClosingAll(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 pb-8">
      <PageHeader
        compact
        title="Dashboard"
        subtitle="Live SENSEX monitor"
        action={
          <div className="flex items-center gap-2">
            {d.persistError ? (
              <span className="rounded border border-rose-500/20 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-600">
                {d.persistError}
              </span>
            ) : null}
            <div className="flex rounded-md border border-[var(--border-subtle)] p-0.5 text-[11px]">
              {(["PAPER", "LIVE"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => {
                    d.setTradingMode(mode);
                    void d.pushSettingsToServer({ trading_mode: mode });
                  }}
                  className={cn(
                    "rounded px-2.5 py-1 font-medium",
                    d.tradingMode === mode
                      ? mode === "LIVE"
                        ? "bg-amber-500 text-white"
                        : "bg-[var(--surface-elevated)] text-[var(--text-primary)]"
                      : "text-[var(--text-muted)]",
                  )}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>
        }
      />

      <PremiumCard compact>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--accent)]" />
            <span className="text-xs font-semibold text-[var(--text-primary)]">Market Status</span>
          </div>
          <MetricBadge
            label="Live Trades"
            value={String(serverOnline ? d.activeTrades.length : 0)}
            tone={d.activeTrades.length > 0 ? "success" : "neutral"}
          />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
          <div className="min-w-0">
            <StatusTile
              label="SENSEX"
              value={livePx != null ? fmtLevel(livePx) : "—"}
              tone={sensexStale ? "warn" : livePx != null ? "ok" : "neutral"}
              large
            />
            {d.showAngelServerRefresh ? (
              <button
                type="button"
                onClick={() => void d.runAngelServerRefresh()}
                disabled={d.angelRefreshBusy}
                className="mt-1 inline-flex items-center gap-1 rounded bg-amber-500 px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-60"
              >
                <RefreshCw className={cn("h-3 w-3", d.angelRefreshBusy && "animate-spin")} />
                {d.angelRefreshBusy ? "Generating token…" : "Generate Token"}
              </button>
            ) : sensexStale && livePx != null ? (
              <p className="mt-0.5 text-[10px] text-amber-600">Last saved quote</p>
            ) : null}
          </div>
          <StatusTile label="Base" value={basePrice != null ? fmtLevel(basePrice) : "—"} />
          <StatusTile
            label="Move"
            value={sessionDiff != null ? `${sessionDiff >= 0 ? "+" : ""}${sessionDiff.toFixed(0)}` : "—"}
            tone={sessionDiff != null ? (sessionDiff >= 0 ? "ok" : "bad") : "neutral"}
          />
          <StatusTile
            label="Today's P&L"
            value={serverOnline ? d.fmtInr(todayPnl) : "—"}
            tone={!serverOnline ? "neutral" : todayPnl >= 0 ? "ok" : "bad"}
          />
          <StatusTile label="Position" value={directionLabel} tone={directionLabel !== "Flat" ? "ok" : "neutral"} />
          <StatusTile label="First Entry" value={d.firstEntryEnabled ? "On" : "Off"} />
          <StatusTile label="Algo" value={d.algoEnabled ? "On" : "Off"} tone={d.algoEnabled ? "ok" : "neutral"} />
          <StatusTile
            label="Engine"
            value={engineCheckPending ? "…" : engineOn ? "Running" : "Stopped"}
            tone={engineOn ? "ok" : "bad"}
          />
          <StatusTile label="Mode" value={d.tradingMode} tone={d.tradingMode === "LIVE" ? "warn" : "neutral"} />
        </div>
      </PremiumCard>

      {!serverOnline && !engineCheckPending ? (
        <PremiumCard compact>
          <div className="flex items-start gap-3 py-2">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">Backend server is offline</p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                Start the Python backend worker to see live trades and strategy ladder.
              </p>
            </div>
          </div>
        </PremiumCard>
      ) : null}

      {serverOnline ? (
        <>
          <CalculatedTradesTable rows={t.calculatedRows} basePrice={basePrice} />

          <PremiumCard compact className="overflow-hidden">
            <CardTitle
              title="Active Trades"
              compact
              subtitle={`${d.activeTrades.length} open position${d.activeTrades.length === 1 ? "" : "s"}`}
              action={
                <button
                  type="button"
                  disabled={d.activeTrades.length === 0 || closingAll}
                  onClick={() => setCloseAllModal(true)}
                  className="rounded border border-rose-500/40 px-2.5 py-1 text-[10px] font-semibold text-rose-600 hover:bg-rose-500/10 disabled:opacity-40"
                >
                  {closingAll ? "Closing all…" : "Close All Trades"}
                </button>
              }
            />
            <div className="overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
              <table className="w-full min-w-[1200px] border-collapse text-xs">
                <thead>
                  <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                    {ACTIVE_COLS.map((h) => (
                      <th
                        key={h || "action"}
                        className="whitespace-nowrap px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.activeTrades.length === 0 ? (
                    <tr>
                      <td colSpan={ACTIVE_COLS.length} className="px-3 py-8 text-center text-sm text-[var(--text-muted)]">
                        No live trades — algo is watching for triggers.
                      </td>
                    </tr>
                  ) : (
                    d.activeTrades.map((a) => (
                      <tr
                        key={a.id}
                        className="border-b border-[var(--border-subtle)]/60 transition-colors last:border-0 hover:bg-[var(--surface-muted)]/40"
                      >
                        <td className="whitespace-nowrap px-3 py-2.5 font-mono font-bold text-[var(--text-primary)]">
                          {a.leg_id}
                        </td>
                        <td className="px-3 py-2.5">
                          <span
                            className={cn(
                              "inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase",
                              /call|ce/i.test(a.side)
                                ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                                : "bg-rose-500/15 text-rose-700 dark:text-rose-400",
                            )}
                          >
                            {a.side}
                          </span>
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-wrap items-center gap-1">
                            <span className={cn("inline-flex rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase", statusClass(a.status))}>
                              {a.status}
                            </span>
                            {a.tp1_hit ? (
                              <span className="inline-flex rounded-md bg-cyan-500/15 px-2 py-0.5 text-[10px] font-semibold text-cyan-700 dark:text-cyan-400">
                                TP1 Hit
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[11px] text-[var(--text-secondary)]">
                          {a.entry_time ? d.formatTradeTimeIST(a.entry_time) : "—"}
                        </td>
                        <td className="max-w-[140px] truncate px-3 py-2.5 font-mono text-[11px]" title={a.symbol ?? ""}>
                          {a.symbol ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 font-mono font-semibold tabular-nums">
                          {a.index_entry != null ? fmtLevel(a.index_entry) : fmtLevel(a.strike)}
                        </td>
                        <td className="px-3 py-2.5 font-mono tabular-nums">
                          {a.entry_price > 0 ? d.fmtInr(a.entry_price) : "Pending"}
                        </td>
                        <td className="px-3 py-2.5 font-mono font-medium tabular-nums">{a.lots}</td>
                        <td className="px-3 py-2.5 font-mono tabular-nums">{a.quantity}</td>
                        <td className="px-3 py-2.5 font-mono tabular-nums text-cyan-700 dark:text-cyan-400">
                          {a.tp1_level != null ? fmtLevel(a.tp1_level) : "—"}
                        </td>
                        <td className="px-3 py-2.5 font-mono tabular-nums text-[var(--text-secondary)]">
                          {a.tp2_trail_level != null ? fmtLevel(a.tp2_trail_level) : "—"}
                        </td>
                        <td className="px-3 py-2.5 font-mono tabular-nums text-rose-600 dark:text-rose-400">
                          {a.sl_level != null ? fmtLevel(a.sl_level) : "—"}
                        </td>
                        <td className="px-3 py-2.5 font-mono tabular-nums">
                          {a.current_price > 0 ? d.fmtInr(a.current_price) : "—"}
                        </td>
                        <td
                          className={cn(
                            "px-3 py-2.5 font-mono font-semibold tabular-nums",
                            a.pnl >= 0 ? "text-emerald-600" : "text-rose-600",
                          )}
                        >
                          {d.fmtInr(a.pnl)}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[10px] text-[var(--text-muted)]">
                          {a.order_id ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <button
                            type="button"
                            onClick={() => void d.closeLegManual(a.leg_id)}
                            className="rounded-md border border-[var(--border-subtle)] px-2 py-1 text-[10px] font-medium hover:bg-[var(--surface-elevated)]"
                          >
                            Close
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {d.activeTrades.some((a) => a.last_order_message && (a.status === "REJECTED" || /reject|fail|denied/i.test(a.last_order_message))) ? (
              <div className="mt-2 space-y-1">
                {d.activeTrades
                  .filter((a) => a.last_order_message && (a.status === "REJECTED" || /reject|fail|denied/i.test(a.last_order_message)))
                  .map((a) => (
                    <p key={a.id} className="rounded-md bg-rose-500/10 px-3 py-1.5 text-[11px] text-rose-600">
                      <span className="font-semibold">{a.leg_id}:</span> {a.last_order_message}
                    </p>
                  ))}
              </div>
            ) : null}
          </PremiumCard>
        </>
      ) : null}

      <PremiumCard compact className="overflow-hidden">
        <CardTitle
          title="Completed Trades"
          compact
          subtitle={serverOnline ? `${completedRows.length} trade${completedRows.length === 1 ? "" : "s"}` : "Server offline"}
          action={
            serverOnline ? (
              <button
                type="button"
                onClick={() => setClearModal(true)}
                disabled={d.completedTrades.length === 0}
                className="rounded border border-rose-500/30 px-2.5 py-1 text-[10px] font-medium text-rose-600 hover:bg-rose-500/10 disabled:opacity-40"
              >
                Clear History
              </button>
            ) : null
          }
        />
        <div className="overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
          <table className="w-full min-w-[1100px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                {COMPLETED_COLS.map((h) => (
                  <th
                    key={h}
                    className="whitespace-nowrap px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!serverOnline ? (
                <tr>
                  <td colSpan={COMPLETED_COLS.length} className="px-3 py-8 text-center text-sm text-[var(--text-muted)]">
                    Server offline — trade history is hidden.
                  </td>
                </tr>
              ) : completedRows.length === 0 ? (
                <tr>
                  <td colSpan={COMPLETED_COLS.length} className="px-3 py-8 text-center text-sm text-[var(--text-muted)]">
                    No completed trades.
                  </td>
                </tr>
              ) : (
                completedRows.map((c) => (
                  <tr key={c.id} className="border-b border-[var(--border-subtle)]/60 last:border-0 hover:bg-[var(--surface-muted)]/40">
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">{d.formatTradeTimeIST(c.entry_time)}</td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">{d.formatTradeTimeIST(c.exit_time)}</td>
                    <td className="px-3 py-2 font-mono font-semibold">{c.leg_id}</td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase",
                          /call|ce/i.test(c.side ?? "")
                            ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                            : "bg-rose-500/15 text-rose-700 dark:text-rose-400",
                        )}
                      >
                        {c.side ?? "—"}
                      </span>
                    </td>
                    <td className="max-w-[120px] truncate px-3 py-2 font-mono text-[11px]" title={c.symbol ?? ""}>
                      {c.symbol ?? "—"}
                    </td>
                    <td className="px-3 py-2 font-mono font-semibold tabular-nums">
                      {c.index_entry != null
                        ? fmtLevel(c.index_entry)
                        : c.strike != null
                          ? fmtLevel(c.strike)
                          : c.range_level != null
                            ? fmtLevel(c.range_level)
                            : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono font-semibold tabular-nums">
                      {c.index_exit != null ? fmtLevel(c.index_exit) : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">{c.lots ?? "—"}</td>
                    <td
                      className={cn(
                        "px-3 py-2 font-mono font-semibold tabular-nums",
                        (c.pnl ?? 0) >= 0 ? "text-emerald-600" : "text-rose-600",
                      )}
                    >
                      {d.fmtInr(c.pnl)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "rounded px-2 py-0.5 text-[10px] font-semibold uppercase",
                          c.trading_mode === "LIVE" ? "bg-amber-500/15 text-amber-700" : "bg-[var(--surface-elevated)] text-[var(--text-muted)]",
                        )}
                      >
                        {c.trading_mode}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[11px]">{fmtExitReason(c.exit_reason)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </PremiumCard>

      <PremiumCard compact className="overflow-hidden">
        <CardTitle
          title="Logs"
          compact
          subtitle={serverOnline ? `${logRows.length} entr${logRows.length === 1 ? "y" : "ies"}` : "Server offline"}
          action={
            serverOnline ? (
              <button
                type="button"
                onClick={() => setClearLogsModal(true)}
                disabled={d.tradingLogs.length === 0 || d.clearingLogs}
                className="rounded border border-rose-500/30 px-2.5 py-1 text-[10px] font-medium text-rose-600 hover:bg-rose-500/10 disabled:opacity-40"
              >
                Clear logs
              </button>
            ) : null
          }
        />
        <div className="overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
          <table className="w-full min-w-[900px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                {LOG_COLS.map((h) => (
                  <th
                    key={h}
                    className="whitespace-nowrap px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!serverOnline ? (
                <tr>
                  <td colSpan={LOG_COLS.length} className="px-3 py-8 text-center text-sm text-[var(--text-muted)]">
                    Server offline — logs are hidden.
                  </td>
                </tr>
              ) : logRows.length === 0 ? (
                <tr>
                  <td colSpan={LOG_COLS.length} className="px-3 py-8 text-center text-sm text-[var(--text-muted)]">
                    No logs yet.
                  </td>
                </tr>
              ) : (
                logRows.map((l) => (
                  <tr key={l.id} className="border-b border-[var(--border-subtle)]/60 last:border-0 hover:bg-[var(--surface-muted)]/40">
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">
                      {d.formatTradeTimeIST(l.created_at)}
                    </td>
                    <td className="px-3 py-2 text-[11px] uppercase text-[var(--text-muted)]">{l.mode || "—"}</td>
                    <td className="px-3 py-2 font-mono text-[11px] font-semibold">{l.action || "—"}</td>
                    <td className="px-3 py-2 font-mono text-[11px]">{l.leg || "—"}</td>
                    <td className="max-w-[120px] truncate px-3 py-2 font-mono text-[11px]" title={l.symbol ?? ""}>
                      {l.symbol ?? "—"}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums">{l.quantity ?? "—"}</td>
                    <td
                      className={cn(
                        "px-3 py-2 font-mono font-semibold tabular-nums",
                        (l.pnl ?? 0) >= 0 ? "text-emerald-600" : "text-rose-600",
                      )}
                    >
                      {l.pnl != null ? d.fmtInr(l.pnl) : "—"}
                    </td>
                    <td className="px-3 py-2 text-[11px]">{l.status ?? "—"}</td>
                    <td className="max-w-[280px] truncate px-3 py-2 text-[11px] text-[var(--text-secondary)]" title={l.message ?? ""}>
                      {l.message ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </PremiumCard>

      <ConfirmModal
        open={clearModal}
        title="Clear completed trades?"
        message="This permanently deletes all completed trade history for your account. Open positions are not affected."
        confirmLabel="Clear History"
        danger
        onCancel={() => setClearModal(false)}
        onConfirm={() => {
          setClearModal(false);
          void d.clearCompletedTrades();
        }}
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
          void d.clearTradingLogs();
        }}
      />

      <ConfirmModal
        open={closeAllModal}
        title="Close all active trades?"
        message={
          d.tradingMode === "LIVE"
            ? `Algo will stop first. ${d.activeTrades.length} active trade(s) will be exited at Angel using MARKET orders; each local trade closes only after broker fill confirmation.`
            : `Algo will stop and all ${d.activeTrades.length} paper trade(s) will close at the current mark price.`
        }
        confirmLabel="Close All Trades"
        danger
        onCancel={() => setCloseAllModal(false)}
        onConfirm={() => {
          setCloseAllModal(false);
          void confirmCloseAll();
        }}
      />

      {d.showAngelServerRefresh && serverOnline ? (
        <PremiumCard compact>
          <button
            type="button"
            onClick={() => void d.runAngelServerRefresh()}
            disabled={d.angelRefreshBusy}
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
          >
            {d.angelRefreshBusy ? "Generating token…" : "Generate Token"}
          </button>
          {d.angelRefreshFeedback ? (
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">{d.angelRefreshFeedback}</p>
          ) : null}
        </PremiumCard>
      ) : null}
    </div>
  );
}
