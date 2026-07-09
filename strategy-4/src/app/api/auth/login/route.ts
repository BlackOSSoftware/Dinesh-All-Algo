import "@/server/env";
import { NextResponse } from "next/server";
import { backendUrl, proxyToBackend } from "@/server/backend-proxy";
import { setAuthCookie } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.text();
  const upstream = await fetch(backendUrl("/auth/login"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    cache: "no-store",
  });
  const data = (await upstream.json().catch(() => ({}))) as {
    access_token?: string;
    detail?: string;
  };

  if (!upstream.ok) {
    return NextResponse.json(
      { ok: false, error: typeof data.detail === "string" ? data.detail : "Login failed" },
      { status: upstream.status },
    );
  }

  if (!data.access_token) {
    return NextResponse.json({ ok: false, error: "Unexpected response from server" }, { status: 502 });
  }

  const response = NextResponse.json({ ok: true, access_token: data.access_token });
  setAuthCookie(response, data.access_token);
  return response;
}
