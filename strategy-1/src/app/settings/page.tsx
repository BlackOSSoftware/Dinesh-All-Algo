"use client";

import { AppShell } from "@/components/trader/app-shell";
import { StrategyView } from "@/components/trader/strategy-view";

export default function SettingsPage() {
  return (
    <AppShell>
      <StrategyView />
    </AppShell>
  );
}
