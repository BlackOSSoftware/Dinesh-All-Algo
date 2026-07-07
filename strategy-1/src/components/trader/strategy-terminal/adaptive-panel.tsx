"use client";

import { fmtLevel } from "@/lib/strategy-reference";
import { PremiumCard, CardTitle } from "@/components/trader/ui/primitives";

function MiniCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
      <p className="font-mono text-xs font-medium text-[var(--text-primary)]">{value}</p>
    </div>
  );
}

export function AdaptivePanel({
  adaptiveHigh,
  adaptiveLow,
  stopDistance,
  tp2Trail,
}: {
  adaptiveHigh: number | null;
  adaptiveLow: number | null;
  stopDistance: number;
  tp2Trail: number;
  liveIndex?: number | null;
}) {
  const callSlTrail = adaptiveHigh != null ? adaptiveHigh - stopDistance : null;
  const putSlTrail = adaptiveLow != null ? adaptiveLow + stopDistance : null;

  return (
    <PremiumCard compact>
      <CardTitle title="Adaptive Extremes & SL Trail" compact />
      <p className="mb-2 text-[11px] text-[var(--text-muted)]">
        Engine tracks session extremes · SL trails ±{stopDistance}pt · TP2 trails {tp2Trail}pt from extreme after core TP1
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2 rounded border border-[var(--border-subtle)] p-2.5">
          <p className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400">Call side</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <MiniCell label="Adaptive High" value={adaptiveHigh != null ? fmtLevel(adaptiveHigh) : "—"} />
            <MiniCell label={`SL trail (−${stopDistance})`} value={callSlTrail != null ? fmtLevel(callSlTrail) : "—"} />
            <MiniCell label="TP2 trail" value={`${tp2Trail} pt`} />
          </div>
        </div>
        <div className="space-y-2 rounded border border-[var(--border-subtle)] p-2.5">
          <p className="text-[10px] font-medium text-rose-600 dark:text-rose-400">Put side</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <MiniCell label="Adaptive Low" value={adaptiveLow != null ? fmtLevel(adaptiveLow) : "—"} />
            <MiniCell label={`SL trail (+${stopDistance})`} value={putSlTrail != null ? fmtLevel(putSlTrail) : "—"} />
            <MiniCell label="TP2 trail" value={`${tp2Trail} pt`} />
          </div>
        </div>
      </div>
    </PremiumCard>
  );
}
