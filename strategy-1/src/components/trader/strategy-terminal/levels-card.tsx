"use client";

import { fmtLevel } from "@/lib/strategy-reference";
import { PremiumCard, CardTitle } from "@/components/trader/ui/primitives";
import type { StrategyLevels, StrategyWorkflowPhase } from "@/lib/strategy-reference";

function LevelCell({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-2.5 py-2">
      <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-semibold text-[var(--text-primary)]">{value}</p>
      {hint ? <p className="mt-0.5 text-[10px] text-[var(--text-muted)]">{hint}</p> : null}
    </div>
  );
}

export function StrategyLevelsCard({
  levels,
  phase,
  capturedCandleTime,
  startTime,
}: {
  levels: StrategyLevels;
  phase: StrategyWorkflowPhase;
  capturedCandleTime: string | null;
  startTime: string;
}) {
  const waiting = phase === "WAITING_SESSION" || phase === "WAITING_BASE";
  const base = waiting ? null : levels.basePrice;

  return (
    <PremiumCard compact className="h-full">
      <CardTitle title="Levels" compact />
      {phase === "WAITING_SESSION" ? (
        <p className="text-xs text-[var(--text-muted)]">
          Waiting for session start ({startTime} IST). No base or triggers yet.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <LevelCell
            label="Base Price"
            value={base != null ? fmtLevel(base) : "—"}
            hint={capturedCandleTime ?? `@ ${startTime}`}
          />
          <LevelCell
            label="Upper Trigger"
            value={levels.upperTrigger != null ? fmtLevel(levels.upperTrigger) : "—"}
            hint="BASE + Gap"
          />
          <LevelCell
            label="Lower Trigger"
            value={levels.lowerTrigger != null ? fmtLevel(levels.lowerTrigger) : "—"}
            hint="BASE − Gap"
          />
        </div>
      )}
    </PremiumCard>
  );
}
