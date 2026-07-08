"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  LogOut,
  BarChart3,
  Moon,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { motion } from "framer-motion";

import { useTheme } from "@/components/trader/theme-provider";
import { clearStoredToken, getApiBase, getStoredToken } from "@/lib/auth";
import { fetchSettings, setAlgoRunning } from "@/lib/strategy3/api";
import type { DashboardMe } from "@/lib/types";
import { cn } from "@/components/ui";

const DashboardUserContext = createContext<DashboardMe | null>(null);
const EngineStatusContext = createContext<{
  engineOn: boolean;
  engineCheckPending: boolean;
  algoRunning: boolean;
  algoCheckPending: boolean;
  setAlgoRunningLocal: (v: boolean) => void;
}>({
  engineOn: false,
  engineCheckPending: true,
  algoRunning: false,
  algoCheckPending: true,
  setAlgoRunningLocal: () => {},
});

export function useDashboardUser(): DashboardMe | null {
  return useContext(DashboardUserContext);
}

export function useEngineStatus() {
  return useContext(EngineStatusContext);
}

function StatusDot({ ok, pending }: { ok: boolean; pending?: boolean }) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        pending ? "bg-[var(--warning)]" : ok ? "bg-[var(--success)]" : "bg-[var(--danger)]",
      )}
    />
  );
}

function AlgoSwitch({ on, onChange }: { on: boolean; onChange: (next: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={cn(
        "relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200",
        on ? "bg-[var(--accent)]" : "bg-[var(--border-strong)]",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200",
          on && "translate-x-5",
        )}
      />
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const [me, setMe] = useState<DashboardMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [engineOn, setEngineOn] = useState(false);
  const [engineCheckPending, setEngineCheckPending] = useState(true);
  const [algoRunning, setAlgoRunningState] = useState(false);
  const [algoCheckPending, setAlgoCheckPending] = useState(false);

  const setAlgoRunningLocal = useCallback((v: boolean) => {
    setAlgoRunningState(v);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const base = getApiBase();

    async function ping() {
      try {
        const res = await fetch(`${base}/health`, { cache: "no-store" });
        const data = (await res.json().catch(() => ({}))) as { status?: string };
        if (!cancelled) {
          setEngineOn(res.ok && data.status === "ok");
          setEngineCheckPending(false);
        }
      } catch {
        if (!cancelled) {
          setEngineOn(false);
          setEngineCheckPending(false);
        }
      }
    }

    void ping();
    const id = window.setInterval(ping, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getStoredToken();
        if (token) {
          const res = await fetch(`${getApiBase()}/users/me`, {
            headers: { Authorization: `Bearer ${token}` },
            cache: "no-store",
          });
          if (res.ok) {
            const data = await res.json();
            if (!cancelled) setMe(data);
            return;
          }
          if (res.status === 401) {
            clearStoredToken();
          }
        }

        const sessionRes = await fetch("/api/auth/session", {
          cache: "no-store",
          credentials: "same-origin",
        });
        const session = (await sessionRes.json().catch(() => ({}))) as {
          authenticated?: boolean;
          user?: DashboardMe;
        };
        if (!cancelled) {
          setMe(sessionRes.ok && session.authenticated && session.user ? session.user : null);
        }
      } catch {
        if (!cancelled) setMe(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!me) return;
    let cancelled = false;

    async function loadAlgo() {
      try {
        const res = await fetchSettings();
        if (!cancelled) {
          setAlgoRunningState(Boolean(res.algo_running));
          setAlgoCheckPending(false);
        }
      } catch {
        if (!cancelled) {
          setAlgoRunningState(false);
          setAlgoCheckPending(false);
        }
      }
    }

    void loadAlgo();
    const id = window.setInterval(() => void loadAlgo(), 12000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [me]);

  async function handleAlgoToggle(next: boolean) {
    setAlgoRunningState(next);
    try {
      await setAlgoRunning(next);
    } catch {
      setAlgoRunningState(!next);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--surface-base)]">
        <p className="text-sm text-[var(--text-muted)]">Loading…</p>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[var(--surface-base)] p-6">
        <p className="text-sm text-[var(--danger)]">Session expired.</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="text-sm text-[var(--accent)] underline"
        >
          Back to login
        </button>
      </div>
    );
  }

  const nav = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/strategy-settings", label: "Strategy Settings", icon: SlidersHorizontal },
    // { href: "/backtest", label: "Backtest", icon: BarChart3 },
  ];

  return (
    <DashboardUserContext.Provider value={me}>
      <EngineStatusContext.Provider
        value={{ engineOn, engineCheckPending, algoRunning, algoCheckPending, setAlgoRunningLocal }}
      >
        <div className="flex h-svh min-h-0 overflow-hidden bg-[var(--surface-base)]">
          <aside className="flex h-full w-[220px] shrink-0 flex-col border-r border-[var(--border-subtle)] bg-[var(--surface-elevated)]">
            <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-4 py-4">
              <p className="text-sm font-semibold text-[var(--text-primary)]">Strategy 3</p>
              <button
                type="button"
                onClick={toggleTheme}
                className="rounded-md p-1.5 text-[var(--text-muted)] transition hover:bg-[var(--surface-muted)] hover:text-[var(--text-primary)]"
                title={theme === "dark" ? "Light mode" : "Dark mode"}
              >
                {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
            </div>

            <nav className="flex-1 space-y-0.5 p-2">
              {nav.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition",
                      active
                        ? "bg-[var(--surface-muted)] text-[var(--text-primary)]"
                        : "text-[var(--text-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--text-primary)]",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0 opacity-70" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>

            <div className="space-y-3 border-t border-[var(--border-subtle)] p-3">
              <div className="flex items-center justify-between gap-3 px-1">
                <div>
                  <p className="text-xs font-medium text-[var(--text-primary)]">Algo</p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    {algoRunning ? "Running" : "Stopped"}
                  </p>
                </div>
                <AlgoSwitch on={algoRunning} onChange={(v) => void handleAlgoToggle(v)} />
              </div>

              <div className="flex items-center justify-between gap-2 rounded-md border border-[var(--border-subtle)] px-3 py-2">
                <p className="text-xs text-[var(--text-secondary)]">Python Engine</p>
                <div className="flex items-center gap-2">
                  <StatusDot ok={engineOn} pending={engineCheckPending} />
                  <span className="text-xs font-medium text-[var(--text-primary)]">
                    {engineCheckPending ? "Checking" : engineOn ? "On" : "Off"}
                  </span>
                </div>
              </div>

              <p className="px-1 text-[11px] text-[var(--text-muted)]">Signed in as {me.username}</p>

              <button
                type="button"
                onClick={async () => {
                  clearStoredToken();
                  await fetch("/api/auth/logout", { method: "POST" });
                  window.location.reload();
                }}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--surface-muted)] hover:text-[var(--text-primary)]"
              >
                <LogOut className="h-3.5 w-3.5" />
                Log out
              </button>
            </div>
          </aside>

          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <main className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6 lg:p-8">
              <motion.div
                key={pathname}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2 }}
              >
                {children}
              </motion.div>
            </main>
          </div>
        </div>
      </EngineStatusContext.Provider>
    </DashboardUserContext.Provider>
  );
}
