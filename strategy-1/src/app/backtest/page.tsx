"use client";

import dynamic from "next/dynamic";
import { AppShell } from "@/components/trader/app-shell";

const BacktestView = dynamic(
  () => import("@/components/trader/backtest-view").then((m) => m.BacktestView),
  {
    loading: () => <p className="py-12 text-center text-sm text-[var(--text-muted)]">Loading backtest…</p>,
    ssr: false,
  },
);

export default function BacktestPage() {
  return (
    <AppShell>
      <BacktestView />
    </AppShell>
  );
}
