import { proxyToBackend } from "@/server/backend-proxy";
import { tokenFromRequest } from "@/lib/auth";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const token = tokenFromRequest(request);
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const body = (await request.json().catch(() => ({}))) as {
    leg_id?: string;
    action?: string;
  };

  if (body.leg_id && body.action === "close") {
    const headers = new Headers({ authorization: `Bearer ${token}`, "content-type": "application/json" });
    const proxied = new Request(request.url, { method: "POST", headers, body: "{}" });
    return proxyToBackend(proxied, `/trading/legs/${encodeURIComponent(body.leg_id)}/close`);
  }

  return NextResponse.json({ ok: false, error: "Unsupported manual order action" }, { status: 400 });
}
