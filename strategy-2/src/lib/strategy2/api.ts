import { getApiBase, getStoredToken } from "@/lib/auth";
import type { DashboardSnapshot, GridBacktestParams, GridBacktestResult, MarketKey, McxExpiryOption, Strategy2Config, TradingMode } from "@/lib/strategy2/types";
import { configToApi } from "@/lib/strategy2/types";

async function apiFetch(path: string, init?: RequestInit) {
  const token = getStoredToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }
  const controller = new AbortController();
  const timeoutMs = path.includes("/dashboard") ? 12000 : 30000;
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${getApiBase()}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg =
        (data as { detail?: string; error?: string }).detail ||
        (data as { error?: string }).error ||
        `Request failed (${res.status})`;
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out — backend may be busy refreshing Angel session. Retrying…");
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function fetchDashboard(): Promise<DashboardSnapshot> {
  return apiFetch("/trading/dashboard") as Promise<DashboardSnapshot>;
}

export async function fetchSettings() {
  return apiFetch("/trading/settings") as Promise<{
    config: Record<string, unknown>;
    algo_running: boolean;
    trading_mode: TradingMode;
  }>;
}

export async function saveSettings(config: Strategy2Config) {
  return apiFetch("/trading/settings", {
    method: "PUT",
    body: JSON.stringify({ config: configToApi(config) }),
  });
}

export async function setAlgoRunning(algo_running: boolean) {
  return apiFetch("/trading/settings", {
    method: "PUT",
    body: JSON.stringify({ algo_running }),
  });
}

export async function setTradingMode(trading_mode: TradingMode) {
  return apiFetch("/trading/settings", {
    method: "PUT",
    body: JSON.stringify({ trading_mode }),
  });
}

export async function clearTradingLogs() {
  return apiFetch("/trading/logs", { method: "DELETE" });
}

export async function closeTradeLeg(legId: string) {
  return apiFetch(`/trading/legs/${encodeURIComponent(legId)}/close`, { method: "POST" });
}

export async function closeAllTrades() {
  return apiFetch("/trading/positions/close-all", { method: "POST" });
}

export async function clearCompletedTrades() {
  return apiFetch("/trading/positions/completed", { method: "DELETE" });
}

export async function fetchMcxExpiries(market: MarketKey, includeExpired = false): Promise<McxExpiryOption[]> {
  const q = new URLSearchParams({ market, includeExpired: includeExpired ? "true" : "false" });
  return apiFetch(`/trading/mcx-expiries?${q.toString()}`) as Promise<McxExpiryOption[]>;
}

export async function runGridBacktest(params: GridBacktestParams): Promise<GridBacktestResult> {
  return apiFetch("/trading/backtest/run", {
    method: "POST",
    body: JSON.stringify(params),
  }) as Promise<GridBacktestResult>;
}
