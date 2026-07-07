import { proxyToBackend } from "@/server/backend-proxy";
import { tokenFromRequest } from "@/lib/auth";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function withAuth(request: Request, path: string) {
  const publicPaths = ["/health"];
  const isPublic = publicPaths.includes(path);

  const token = tokenFromRequest(request);
  if (!token && !isPublic) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const headers = new Headers(request.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  const proxied = new Request(request.url, {
    method: request.method,
    headers,
    body: request.method !== "GET" && request.method !== "HEAD" ? await request.text() : undefined,
  });
  return proxyToBackend(proxied, path);
}

export async function GET(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return withAuth(request, `/${path.join("/")}`);
}

export async function POST(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return withAuth(request, `/${path.join("/")}`);
}

export async function PUT(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return withAuth(request, `/${path.join("/")}`);
}

export async function DELETE(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return withAuth(request, `/${path.join("/")}`);
}

export async function PATCH(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return withAuth(request, `/${path.join("/")}`);
}
