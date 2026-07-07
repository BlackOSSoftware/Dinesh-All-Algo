"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy2SettingsView } from "@/components/strategy2/settings-view";

export default function StrategySettingsPage() {
  return (
    <AppShell>
      <Strategy2SettingsView />
    </AppShell>
  );
}
