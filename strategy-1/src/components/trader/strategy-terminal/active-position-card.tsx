"use client";

import { fmtLevel } from "@/lib/strategy-reference";
import { cn } from "@/components/ui";
import { PremiumCard, CardTitle } from "@/components/trader/ui/primitives";

type ActiveRow = {
  leg_id: string;
  side: string;
  strike: number;
  lots: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  status: string;
};

function tradeTypeLabel(legId: string, side: string): string {
  const id = legId.toUpperCase();
  const isCall = /call|ce/i.test(side);
  if (/avg|average/i.test(id)) return isCall ? "Call Avg" : "Put Avg";
  if (/re.?entry/i.test(id)) return isCall ? "Call Re-entry" : "Put Re-entry";
  return isCall ? "Initial Call" : "Initial Put";
}

function Cell({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div>
      <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
      <p
        className={cn(
          "font-mono text-xs font-medium",
          tone === "up" ? "text-emerald-600" : tone === "down" ? "text-rose-600" : "text-[var(--text-primary)]",
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function ActivePositionCard({
  trade,
  levels,
  tp1,
  tp2Trail,
  stoploss,
}: {
  trade: ActiveRow | null;
  levels: { upperTrigger: number | null; lowerTrigger: number | null };
  tp1: number | null;
  tp2Trail: number | null;
  stoploss: number | null;
}) {
  return (
    <PremiumCard compact className="h-full">
      <CardTitle title="Active Position" compact />
      {!trade ? (
        <p className="text-xs text-[var(--text-muted)]">
          No position. Watching {fmtLevel(levels.upperTrigger)} / {fmtLevel(levels.lowerTrigger)}.
        </p>
      ) : (
        <div className="grid grid-cols-4 gap-x-3 gap-y-2 sm:grid-cols-8">
          <Cell label="Type" value={tradeTypeLabel(trade.leg_id, trade.side)} />
          <Cell label="Entry" value={fmtLevel(trade.strike)} />
          <Cell label="Lots" value={String(trade.lots)} />
          <Cell label="TP1" value={tp1 != null ? fmtLevel(tp1) : "—"} />
          <Cell label="TP2 Trail" value={tp2Trail != null ? `${tp2Trail} pt` : "—"} />
          <Cell label="SL" value={stoploss != null ? fmtLevel(stoploss) : "—"} tone="down" />
          <Cell label="Mark" value={fmtLevel(trade.current_price)} />
          <Cell label="PnL" value={fmtLevel(trade.pnl)} tone={trade.pnl >= 0 ? "up" : "down"} />
        </div>
      )}
    </PremiumCard>
  );
}
