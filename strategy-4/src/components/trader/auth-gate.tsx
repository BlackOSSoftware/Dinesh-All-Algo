"use client";

import Image from "next/image";
import { FormEvent, useEffect, useState } from "react";
import { setStoredToken, getStoredToken, getApiBase } from "@/lib/auth";
import { ThemeProvider } from "@/components/trader/theme-provider";

type AuthState = "checking" | "authenticated" | "guest";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>("checking");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;

    async function checkSession() {
      const token = getStoredToken();
      if (token) {
        try {
          const res = await fetch(`${getApiBase()}/users/me`, {
            headers: { Authorization: `Bearer ${token}` },
            cache: "no-store",
          });
          if (!alive) return;
          if (res.ok) {
            setState("authenticated");
            return;
          }
          if (res.status === 401) {
            localStorage.removeItem("indian_algo_token");
          }
        } catch {
          /* fall through to cookie session */
        }
      }

      try {
        const res = await fetch("/api/auth/session", { cache: "no-store", credentials: "same-origin" });
        const data = (await res.json()) as { authenticated?: boolean };
        if (!alive) return;
        setState(data.authenticated ? "authenticated" : "guest");
      } catch {
        if (alive) setState("guest");
      }
    }

    void checkSession();
    return () => {
      alive = false;
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, password }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        access_token?: string;
        error?: string;
        detail?: string;
      };
      if (!res.ok) {
        setError(data.error ?? data.detail ?? "Login failed");
        return;
      }
      if (data.access_token) setStoredToken(data.access_token);
      setState("authenticated");
    } catch (err) {
      const reason = err instanceof Error ? err.message : "Network error";
      setError(
        `Cannot reach API — ${reason}. Start the engine: npm run worker (port 8003), then npm run dev (port 3003).`,
      );
    } finally {
      setLoading(false);
    }
  }

  if (state === "authenticated") return <>{children}</>;

  if (state === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-200 border-t-teal-600" />
      </div>
    );
  }

  return (
    <ThemeProvider>
      <div className="flex min-h-screen flex-col bg-slate-100 lg:flex-row">
        <div className="relative min-h-[240px] w-full lg:min-h-screen lg:w-[46%]">
          <Image
            src="https://images.unsplash.com/photo-1611974789855-9c2a0a6286d6?q=80&w=2000&auto=format&fit=crop"
            alt="Markets"
            fill
            priority
            className="object-cover"
            sizes="(max-width: 1024px) 100vw, 46vw"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-white/95 via-white/40 to-transparent lg:bg-gradient-to-r lg:from-white/90 lg:via-white/35 lg:to-transparent" />
          <div className="absolute bottom-8 left-8 right-8 space-y-2 lg:bottom-16 lg:left-10 lg:right-10">
            <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-teal-600">Strategy 4</p>
            <h1 className="text-3xl font-semibold leading-tight tracking-tight text-slate-900 sm:text-4xl">
              Indian Algo — Strategy 4
            </h1>
            <p className="max-w-md text-sm leading-relaxed text-slate-600">
              Default sign-in: username{" "}
              <span className="rounded bg-teal-50 px-1.5 py-0.5 font-mono text-xs font-medium text-teal-800 ring-1 ring-teal-100">
                admin
              </span>{" "}
              and password{" "}
              <span className="rounded bg-teal-50 px-1.5 py-0.5 font-mono text-xs font-medium text-teal-800 ring-1 ring-teal-100">
                admin
              </span>
              .
            </p>
          </div>
        </div>

        <div className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10">
          <div className="w-full max-w-md space-y-8">
            <div className="space-y-2 text-center lg:text-left">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Welcome back</h2>
              <p className="text-sm text-slate-500">Sign in to open the trading dashboard.</p>
            </div>

            <form
              onSubmit={onSubmit}
              className="space-y-5 rounded-2xl border border-slate-200/90 bg-white p-6 shadow-[0_4px_40px_-12px_rgba(15,23,42,0.12)] sm:p-8"
            >
              <label className="block space-y-2">
                <span className="text-sm font-medium text-slate-700">Username</span>
                <input
                  className="w-full rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-teal-400 focus:bg-white focus:ring-2 focus:ring-teal-100"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </label>
              <label className="block space-y-2">
                <span className="text-sm font-medium text-slate-700">Password</span>
                <input
                  type="password"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-teal-400 focus:bg-white focus:ring-2 focus:ring-teal-100"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </label>

              {error ? (
                <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p>
              ) : null}

              <button
                type="submit"
                disabled={loading}
                className="flex w-full items-center justify-center rounded-xl bg-gradient-to-r from-teal-600 to-teal-500 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:from-teal-700 hover:to-teal-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? "Signing in…" : "Login"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </ThemeProvider>
  );
}
