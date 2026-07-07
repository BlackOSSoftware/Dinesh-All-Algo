import { NextResponse } from "next/server";
import { backendUrl } from "@/server/backend-proxy";
import { tokenFromRequest } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const token = tokenFromRequest(request);
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const headers = { authorization: `Bearer ${token}` };

  try {
    const [healthRes, settingsRes, activeRes, logsRes] = await Promise.all([
      fetch(backendUrl("/health"), { cache: "no-store" }),
      fetch(backendUrl("/trading/settings"), { headers, cache: "no-store" }),
      fetch(backendUrl("/trading/positions/active"), { headers, cache: "no-store" }),
      fetch(backendUrl("/trading/logs?limit=50"), { headers, cache: "no-store" }),
    ]);

    const health = await healthRes.json().catch(() => ({}));
    const settings = settingsRes.ok ? await settingsRes.json().catch(() => null) : null;
    const active = activeRes.ok ? await activeRes.json().catch(() => []) : [];
    const logs = logsRes.ok ? await logsRes.json().catch(() => []) : [];

    return NextResponse.json({
      status: {
        connected: healthRes.ok && health.status === "ok",
        engine: health,
      },
      settings,
      activePositions: active,
      recentLogs: logs,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Snapshot failed" },
      { status: 502 },
    );
  }
}
