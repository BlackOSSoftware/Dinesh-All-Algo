"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy3SettingsView } from "@/components/strategy3/settings-view";

export default function StrategySettingsPage() {
  return (
    <AppShell>
      <Strategy3SettingsView />
    </AppShell>
  );
}
