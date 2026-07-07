"use client";

import { WORKFLOW_STEPS, type StrategyWorkflowPhase } from "@/lib/strategy-reference";
import { cn } from "@/components/ui";
import { PremiumCard, CardTitle } from "@/components/trader/ui/primitives";

const PHASE_ORDER: StrategyWorkflowPhase[] = WORKFLOW_STEPS.map((s) => s.phase);

function phaseIndex(p: StrategyWorkflowPhase): number {
  const i = PHASE_ORDER.indexOf(p);
  return i >= 0 ? i : 0;
}

export function StrategyWorkflowPanel({ phase }: { phase: StrategyWorkflowPhase }) {
  const current = phaseIndex(phase);
  const label = WORKFLOW_STEPS.find((s) => s.phase === phase)?.label ?? phase.replace(/_/g, " ");

  return (
    <PremiumCard compact>
      <CardTitle title="Workflow" compact action={<span className="text-xs font-medium text-[var(--accent)]">{label}</span>} />
      <div className="flex flex-wrap gap-1">
        {WORKFLOW_STEPS.map((step, idx) => {
          const done = idx < current;
          const active = step.phase === phase || (phase === "CYCLE_OPEN" && step.phase === "WATCHING_TRIGGERS");
          return (
            <span
              key={step.phase}
              className={cn(
                "rounded px-2 py-0.5 text-[10px] font-medium",
                active
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : done
                    ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "bg-[var(--surface-muted)] text-[var(--text-muted)]",
              )}
            >
              {step.label}
            </span>
          );
        })}
      </div>
    </PremiumCard>
  );
}
