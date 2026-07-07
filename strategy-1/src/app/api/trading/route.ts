import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as { enabled?: boolean };
  return NextResponse.json({
    ok: true,
    enabled: Boolean(body.enabled),
    message: "Trading engine runs in the Python worker (npm run worker).",
  });
}
