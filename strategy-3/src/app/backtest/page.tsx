"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy3BacktestView } from "@/components/strategy3/backtest-view";

export default function BacktestPage() {
  return (
    <AppShell>
      <Strategy3BacktestView />
    </AppShell>
  );
}
