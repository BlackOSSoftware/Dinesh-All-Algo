"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy2BacktestView } from "@/components/strategy2/backtest-view";

export default function BacktestPage() {
  return (
    <AppShell>
      <Strategy2BacktestView />
    </AppShell>
  );
}
