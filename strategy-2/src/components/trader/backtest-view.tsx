"use client";

import { PageHeader, PremiumCard } from "@/components/trader/ui/primitives";

export function BacktestView() {
  return (
    <div className="mx-auto max-w-3xl space-y-6 pb-10">
      <PageHeader title="Backtest" subtitle="Strategy 2 backtest — historical simulation will be built here." />

      <PremiumCard className="!p-6">
        <p className="text-sm text-[var(--text-secondary)]">
          Strategy 1 backtest engine removed. Backtest UI for Strategy 2 will be added separately.
        </p>
      </PremiumCard>
    </div>
  );
}
