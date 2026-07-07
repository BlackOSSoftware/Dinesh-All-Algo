"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy4SettingsView } from "@/components/strategy4/settings-view";

export default function StrategySettingsPage() {
  return (
    <AppShell>
      <Strategy4SettingsView />
    </AppShell>
  );
}
