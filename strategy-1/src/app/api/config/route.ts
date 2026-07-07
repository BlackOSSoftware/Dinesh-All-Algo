import { proxyToBackend } from "@/server/backend-proxy";
import { tokenFromRequest } from "@/lib/auth";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const token = tokenFromRequest(request);
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const headers = new Headers(request.headers);
  headers.set("authorization", `Bearer ${token}`);
  const proxied = new Request(request.url, { method: "GET", headers });
  return proxyToBackend(proxied, "/trading/settings");
}

export async function PUT(request: Request) {
  const token = tokenFromRequest(request);
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const headers = new Headers(request.headers);
  headers.set("authorization", `Bearer ${token}`);
  const proxied = new Request(request.url, {
    method: "PUT",
    headers,
    body: await request.text(),
  });
  return proxyToBackend(proxied, "/trading/settings");
}
