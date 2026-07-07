import { NextResponse } from "next/server";

export const AUTH_COOKIE = "indian_algo_token";

export function getApiBase(): string {
  if (typeof window !== "undefined") {
    return "/api/backend";
  }
  const base = process.env.BACKEND_PROXY_URL ?? "http://127.0.0.1:8000";
  return base.replace(/\/$/, "");
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_COOKIE);
}

export function setStoredToken(token: string) {
  localStorage.setItem(AUTH_COOKIE, token);
}

export function clearStoredToken() {
  localStorage.removeItem(AUTH_COOKIE);
}

export function tokenFromRequest(request: Request): string | null {
  const auth = request.headers.get("authorization");
  if (auth?.startsWith("Bearer ")) return auth.slice(7);
  const cookie = request.headers.get("cookie") ?? "";
  const match = cookie.match(new RegExp(`(?:^|; )${AUTH_COOKIE}=([^;]+)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

export function setAuthCookie(response: NextResponse, token: string) {
  response.cookies.set(AUTH_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
}

export function clearAuthCookie(response: NextResponse) {
  response.cookies.set(AUTH_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}
