"use client";

import { Layers } from "lucide-react";

import { fmtLevel, type CalculatedTradeRow } from "@/lib/strategy-reference";
import { PremiumCard, CardTitle } from "@/components/trader/ui/primitives";
import { cn } from "@/components/ui";

function statusBadge(status: string) {
  const s = status.toLowerCase();
  if (s.includes("triggered") || s.includes("at/above") || s.includes("at/below"))
    return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400";
  if (s.includes("waiting") || s === "—")
    return "bg-[var(--surface-elevated)] text-[var(--text-muted)]";
  return "bg-amber-500/10 text-amber-700 dark:text-amber-400";
}

export function CalculatedTradesTable({ rows, basePrice }: { rows: CalculatedTradeRow[]; basePrice?: number | null }) {
  return (
    <PremiumCard compact className="overflow-hidden">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)]">
            <Layers className="h-4 w-4 text-[var(--accent)]" />
          </div>
          <div>
            <CardTitle title="Strategy Ladder" compact />
            <p className="text-[11px] text-[var(--text-muted)]">
              Planned entry · TP1 · TP2 trail · SL levels
              {basePrice != null ? ` · Base ${fmtLevel(basePrice)}` : ""}
            </p>
          </div>
        </div>
        <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-2.5 py-1 text-[10px] font-medium text-[var(--text-secondary)]">
          {rows.length} level{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border-subtle)] py-8 text-center">
          <p className="text-sm text-[var(--text-muted)]">Waiting for base price capture at session start.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--border-subtle)]">
          <table className="w-full min-w-[920px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                {["Type", "Side", "Entry Level", "Lots", "TP1", "TP2 Trail", "Stop Loss", "Status"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className={cn(
                    "border-b border-[var(--border-subtle)]/60 transition-colors last:border-0 hover:bg-[var(--surface-muted)]/50",
                    row.side === "CALL"
                      ? "bg-gradient-to-r from-emerald-500/[0.04] to-transparent"
                      : "bg-gradient-to-r from-rose-500/[0.04] to-transparent",
                  )}
                >
                  <td className="px-3 py-2.5">
                    <span className="font-medium text-[var(--text-primary)]">{row.tradeType}</span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                        row.side === "CALL"
                          ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                          : "bg-rose-500/15 text-rose-700 dark:text-rose-400",
                      )}
                    >
                      {row.side}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-sm font-semibold tabular-nums text-[var(--text-primary)]">
                    {fmtLevel(row.entryLevel)}
                  </td>
                  <td className="px-3 py-2.5 font-mono font-medium tabular-nums">{row.lots}</td>
                  <td className="px-3 py-2.5 font-mono tabular-nums text-cyan-700 dark:text-cyan-400">
                    {fmtLevel(row.tp1)}
                  </td>
                  <td className="px-3 py-2.5 font-mono tabular-nums text-[var(--text-secondary)]">
                    {row.tp2Trail != null ? `${row.tp2Trail} pt` : "—"}
                  </td>
                  <td className="px-3 py-2.5 font-mono tabular-nums text-rose-600 dark:text-rose-400">
                    {fmtLevel(row.stoploss)}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={cn("inline-flex rounded-md px-2 py-0.5 text-[10px] font-medium", statusBadge(row.status))}>
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PremiumCard>
  );
}
