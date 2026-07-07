import { NextResponse } from "next/server";
import { backendUrl, proxyToBackend } from "@/server/backend-proxy";
import { tokenFromRequest } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const token = tokenFromRequest(request);
  if (!token) {
    return NextResponse.json({ authenticated: false });
  }

  try {
    const upstream = await fetch(backendUrl("/users/me"), {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!upstream.ok) {
      return NextResponse.json({ authenticated: false });
    }
    const user = await upstream.json();
    return NextResponse.json({ authenticated: true, user });
  } catch {
    return NextResponse.json({ authenticated: false });
  }
}
