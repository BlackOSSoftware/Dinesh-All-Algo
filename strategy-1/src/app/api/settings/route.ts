import { proxyToBackend } from "@/server/backend-proxy";
import { tokenFromRequest } from "@/lib/auth";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function authedProxy(request: Request, path: string) {
  const token = tokenFromRequest(request);
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const headers = new Headers(request.headers);
  headers.set("authorization", `Bearer ${token}`);
  const proxied = new Request(request.url, {
    method: request.method,
    headers,
    body: request.method !== "GET" && request.method !== "HEAD" ? await request.text() : undefined,
  });
  return proxyToBackend(proxied, path);
}

export async function GET(request: Request) {
  return authedProxy(request, "/trading/settings");
}

export async function PUT(request: Request) {
  return authedProxy(request, "/trading/settings");
}
