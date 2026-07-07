"use client";

import { AppShell } from "@/components/trader/app-shell";
import { DashboardHome } from "@/components/trader/dashboard-home";

export default function HomePage() {
  return (
    <AppShell>
      <DashboardHome />
    </AppShell>
  );
}
