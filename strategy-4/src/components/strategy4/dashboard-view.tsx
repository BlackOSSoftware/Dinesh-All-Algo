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

function fmtPx(v: number) {
  if (!Number.isFinite(v) || v === 0) return "—";
  return v.toFixed(2);
}

function fmtPnl(v: number) {
  if (!Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

function fmtDelta(v: number) {
  if (!Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

function phaseLabel(phase: string | undefined) {
  switch ((phase || "").toUpperCase()) {
    case "IDLE":
      return "Idle";
    case "WAIT_REF":
      return "Waiting reference close";
    case "WAIT_BREAKOUT":
      return "Armed — waiting breakout";
    case "IN_TRADE":
      return "In trade";
    case "REVERSE_TRADE":
      return "Reverse trade";
    case "DONE":
      return "Done for today";
    case "NO_TRADE":
      return "No trade";
    default:
      return phase || "—";
  }
}

function PriceBox({ quote, active }: { quote: MarketQuote | undefined; active?: boolean }) {
  if (!quote) {
    return (
      <PremiumCard className="!p-4">
        <CardTitle title="—" compact />
        <p className="text-2xl font-semibold text-[var(--text-primary)]">—</p>
      </PremiumCard>
    );
  }
  const label = quote.label;
  const isLive = quote.market_open && quote.source === "live";
  const tag =
    quote.price_type === "CLOSE"
      ? "Prev close"
      : isLive
        ? "LTP · Live"
        : quote.price > 0
          ? "LTP · Last"
          : "Last price";
  return (
    <PremiumCard
      className={cn(
        "!p-4",
        active && "ring-2 ring-[var(--accent)] ring-offset-2 ring-offset-[var(--bg)]",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <CardTitle title={label} compact />
        <div className="flex items-center gap-1.5">
          {active ? (
            <span className="rounded-full bg-[var(--accent)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
              Trading
            </span>
          ) : null}
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              isLive ? "bg-[var(--success-soft)] text-[var(--success)]" : "bg-[var(--warning-soft)] text-[var(--warning)]",
            )}
          >
            {tag}
          </span>
        </div>
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-[var(--text-primary)]">{fmtPx(quote.price)}</p>
      {quote.tradingsymbol ? (
        <p className="mt-1 text-[11px] text-[var(--text-muted)]">{quote.tradingsymbol}</p>
      ) : null}
      {quote.error && quote.price <= 0 ? (
        <p className="mt-1 text-[11px] text-[var(--danger)]">{quote.error}</p>
      ) : null}
    </PremiumCard>
  );
}

function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-[var(--text-primary)]">{children}</dd>
    </div>
  );
}

function BreakdownPanel({ data }: { data: DashboardSnapshot | null | undefined }) {
  const market = data?.market || String(data?.config?.market || "") || "—";
  const symbol = data?.active_symbol || "—";
  const phase = data?.phase || "";
  const cmp = data?.current_market_price ?? 0;
  const priceType = data?.price_type === "CLOSE" ? "Prev close" : data?.price_type || "LTP";
  const ref = data?.reference_price ?? 0;
  const buy = data?.buy_trigger ?? 0;
  const sell = data?.sell_trigger ?? 0;
  const tpPts = data?.take_profit_pts ?? 0;
  const slPts = data?.stop_loss_pts ?? 0;
  const lots = data?.lots ?? 0;
  const dist = data?.breakout_distance ?? 0;

  const pendingTrade = useMemo(() => {
    if ((phase || "").toUpperCase() !== "WAIT_BREAKOUT" || ref <= 0) return null;
    return {
      buyLine: `If LTP/close >= ${fmtPx(buy)} -> BUY ${lots} lot @ fill · TP ${fmtPx(buy + tpPts)} · SL ${fmtPx(buy - slPts)}`,
      sellLine: `If LTP/close <= ${fmtPx(sell)} -> SELL ${lots} lot @ fill · TP ${fmtPx(sell - tpPts)} · SL ${fmtPx(sell + slPts)}`,
    };
  }, [phase, ref, buy, sell, lots, tpPts, slPts]);

  const blockers: string[] = [];
  if (data && !data.algo_running) blockers.push("Algo is stopped — enable algo to trade.");
  if (data && data.in_session === false) blockers.push("Outside session window — engine ignores price ticks.");
  if ((phase || "").toUpperCase() === "WAIT_REF") blockers.push("Waiting for start-time candle close as reference.");
  if ((phase || "").toUpperCase() === "WAIT_BREAKOUT" && cmp > 0 && buy > 0 && sell > 0 && cmp < buy && cmp > sell) {
    blockers.push("Price is between buy & sell triggers — no breakout yet.");
  }
  if (data?.last_live_error) blockers.push(data.last_live_error);

  return (
    <PremiumCard className="!p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle title="Strategy Breakdown" subtitle="Live state — what is armed and what trade will form" />
        </div>
        <span
          className={cn(
            "rounded-full px-3 py-1 text-[11px] font-semibold",
            data?.algo_running
              ? "bg-[var(--success-soft)] text-[var(--success)]"
              : "bg-[var(--surface-muted)] text-[var(--text-muted)]",
          )}
        >
          {phaseLabel(phase)}
        </span>
      </div>

      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Active market">
          {market.replace(/_/g, " ")}
        </Metric>
        <Metric label="Symbol trading">{symbol}</Metric>
        <Metric label="Session">
          {data?.session_start || "—"} – {data?.session_end || "—"}
          {data?.in_session != null ? (
            <span className={cn("ml-2 text-[11px]", data.in_session ? "text-[var(--success)]" : "text-[var(--warning)]")}>
              {data.in_session ? "· In session" : "· Outside session"}
            </span>
          ) : null}
        </Metric>
        <Metric label="Lots / Distance">
          {lots || "—"} lot · breakout ±{dist || "—"}
        </Metric>
      </dl>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-3">
          <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Current price ({priceType})</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-[var(--text-primary)]">{fmtPx(cmp)}</p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            This close/LTP is used for breakout checks on <span className="font-medium text-[var(--text-secondary)]">{symbol}</span>
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-3">
          <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Reference close</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-[var(--text-primary)]">{fmtPx(ref)}</p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Start candle {data?.ref_candle_time || data?.session_start || "—"} · Buy {fmtPx(buy)} · Sell {fmtPx(sell)}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-3">
          <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Distance to triggers</p>
          <p className="mt-1 text-sm tabular-nums text-[var(--text-primary)]">
            BUY {fmtDelta(buy > 0 && cmp > 0 ? buy - cmp : NaN)} · SELL {fmtDelta(sell > 0 && cmp > 0 ? cmp - sell : NaN)}
          </p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            TP ±{tpPts || "—"} · SL ±{slPts || "—"}
            {data?.active_side ? ` · Side ${data.active_side}${data.is_reverse ? " (reverse)" : ""}` : ""}
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-[var(--border-subtle)] p-3">
        <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Next / pending trade</p>
        <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
          {data?.next_action_level || data?.status_message || "—"}
        </p>
        {pendingTrade ? (
          <ul className="mt-2 space-y-1 text-xs text-[var(--text-primary)]">
            <li>• {pendingTrade.buyLine}</li>
            <li>• {pendingTrade.sellLine}</li>
          </ul>
        ) : null}
        {(phase || "").toUpperCase() === "IN_TRADE" || (phase || "").toUpperCase() === "REVERSE_TRADE" ? (
          <p className="mt-2 text-xs tabular-nums text-[var(--text-primary)]">
            Open {data?.is_reverse ? "Reverse" : "Initial"} {data?.active_side || "—"} · Entry {fmtPx(data?.entry_price ?? 0)} ·
            TP {fmtPx(data?.tp_price ?? 0)} · SL {fmtPx(data?.sl_price ?? 0)}
          </p>
        ) : null}
      </div>

      {blockers.length > 0 ? (
        <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-100">
          <p className="font-semibold">Why trade may not fire</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </PremiumCard>
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
                <tr key={i} className="border-b border-[var(--border-subtle)] last:border-0">
                  {row.map((cell, j) => (
                    <td key={j} className="max-w-[28rem] px-3 py-2 whitespace-pre-wrap break-words text-[var(--text-primary)]">
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
    <div className="mx-auto max-w-6xl space-y-6 pb-10">
      <PageHeader title="Dashboard" subtitle="Strategy 4 — MCX single breakout + reverse entry" />

      {error ? (
        <p className="rounded-xl border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-4 py-3 text-sm text-[var(--danger)]">{error}</p>
      ) : null}

      {!serverOnline ? (
        <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Server offline — active trades, completed trades, and logs are hidden until the server is back.
        </p>
      ) : null}

      <AngelTokenRefreshBanner show={showAngelTokenRefresh} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {quotes.map((quote) => (
          <PriceBox key={quote.key} quote={quote} active={quote.key.toUpperCase() === selectedMarket} />
        ))}
      </div>

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
            <button
              type="button"
              disabled={busy}
              onClick={() => void changeMode("PAPER")}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium",
                data?.trading_mode === "PAPER"
                  ? "bg-[var(--accent)] text-white"
                  : "border border-[var(--border-subtle)] text-[var(--text-secondary)]",
              )}
            >
              Paper
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void changeMode("LIVE")}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium",
                data?.trading_mode === "LIVE"
                  ? "bg-[var(--accent)] text-white"
                  : "border border-[var(--border-subtle)] text-[var(--text-secondary)]",
              )}
            >
              Live
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Algo: {data?.algo_running ? "Running" : "Stopped"} · Mode: {data?.trading_mode ?? "PAPER"}
          {selectedMarket ? ` · Market: ${selectedMarket.replace(/_/g, " ")}` : ""}
          {data?.active_symbol ? ` · Symbol: ${data.active_symbol}` : ""}
        </p>
      </PremiumCard>

      <BreakdownPanel data={data} />

      <div className="grid gap-4 lg:grid-cols-2">
        <PremiumCard className="!p-0 overflow-hidden">
          <div className="border-b border-[var(--border-subtle)] px-4 py-3">
            <CardTitle title={`Breakout Levels · Ref ${fmtPx(data?.reference_price ?? 0)}`} compact />
            {data?.active_symbol ? (
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                Symbol: <span className="font-medium text-[var(--text-secondary)]">{data.active_symbol}</span>
                {data.active_side ? ` · ${data.is_reverse ? "Reverse " : ""}${data.active_side}` : " · Waiting breakout"}
              </p>
            ) : (
              <p className="mt-1 text-xs text-[var(--text-muted)]">Select market in Strategy Settings</p>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                  <th className="px-3 py-2">Level</th>
                  <th className="px-3 py-2">Price</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {(data?.grid_levels ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-[var(--text-muted)]">
                      Save strategy settings and enable algo to arm breakout levels
                    </td>
                  </tr>
                ) : (
                  data?.grid_levels.map((row) => (
                    <tr key={row.level} className="border-b border-[var(--border-subtle)] last:border-0">
                      <td className="px-3 py-2 font-medium">{row.level}</td>
                      <td className="px-3 py-2 tabular-nums">{fmtPx(row.price)}</td>
                      <td className="px-3 py-2">{row.action}</td>
                      <td className="px-3 py-2">{row.status}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </PremiumCard>

        <PremiumCard className="!p-4">
          <CardTitle title="Live Position" />
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Current Position Lots</dt>
              <dd className="text-lg font-semibold tabular-nums">{data?.position_lots ?? 0}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Realized P&amp;L</dt>
              <dd className="text-lg font-semibold tabular-nums">{fmtPnl(data?.realized_pnl ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Unrealized P&amp;L</dt>
              <dd className="text-lg font-semibold tabular-nums">{fmtPnl(data?.unrealized_pnl ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Current Market Price</dt>
              <dd className="text-lg font-semibold tabular-nums">{fmtPx(data?.current_market_price ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Phase</dt>
              <dd className="text-sm font-medium">{phaseLabel(data?.phase)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Trades Today</dt>
              <dd className="text-lg font-semibold tabular-nums">{data?.trade_count ?? 0}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Buy Trigger</dt>
              <dd className="text-lg font-semibold tabular-nums">{fmtPx(data?.buy_trigger ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Sell Trigger</dt>
              <dd className="text-lg font-semibold tabular-nums">{fmtPx(data?.sell_trigger ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-[10px] text-[var(--text-muted)]">Entry / TP / SL</dt>
              <dd className="text-sm font-medium tabular-nums">
                {fmtPx(data?.entry_price ?? 0)} / {fmtPx(data?.tp_price ?? 0)} / {fmtPx(data?.sl_price ?? 0)}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[10px] text-[var(--text-muted)]">Status</dt>
              <dd className="text-sm text-[var(--text-secondary)]">{data?.status_message || data?.next_action_level || "—"}</dd>
            </div>
          </dl>
        </PremiumCard>
      </div>

      <DataTable
        title="Active Trades"
        headers={["Trade Time", "Side", "Leg", "Lots", "Entry", "Mark", "P&L", "Mode"]}
        rows={activeTrades.map((t) => [
          fmtDateTime(t.entry_time),
          t.side || "—",
          t.leg_id,
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
        headers={["Entry Time", "Exit Time", "Leg", "Symbol", "Entry", "Exit", "P&L", "Reason"]}
        rows={completedTrades.map((t) => [
          fmtDateTime(t.entry_time),
          fmtDateTime(t.exit_time),
          t.leg_id,
          t.symbol ?? "—",
          fmtPx(t.entry_price ?? 0),
          fmtPx(t.exit_price ?? 0),
          fmtPnl(t.pnl ?? 0),
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
