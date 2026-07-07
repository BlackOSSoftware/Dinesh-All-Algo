"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy4BacktestView } from "@/components/strategy4/backtest-view";

export default function BacktestPage() {
  return (
    <AppShell>
      <Strategy4BacktestView />
    </AppShell>
  );
}
