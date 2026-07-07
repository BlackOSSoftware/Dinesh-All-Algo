"use client";

import { AppShell } from "@/components/trader/app-shell";
import { Strategy3DashboardView } from "@/components/strategy3/dashboard-view";

export default function HomePage() {
  return (
    <AppShell>
      <Strategy3DashboardView />
    </AppShell>
  );
}
