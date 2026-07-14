"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiBase } from "@/lib/auth";
import {
  clearCompletedTrades as apiClearCompleted,
  clearTradingLogs as apiClearLogs,
  fetchDashboard,
} from "@/lib/strategy4/api";
import { EMPTY_DASHBOARD, type DashboardSnapshot } from "@/lib/strategy4/types";

const SNAPSHOT_KEY = "strategy4_dashboard_snapshot";
const HEALTH_MS = 8000;

function loadCachedSnapshot(): DashboardSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(SNAPSHOT_KEY);
    return raw ? (JSON.parse(raw) as DashboardSnapshot) : null;
  } catch {
    return null;
  }
}

function stripTradeData(snap: DashboardSnapshot): DashboardSnapshot {
  return {
    ...snap,
    active_trades: [],
    completed_trades: [],
    logs: [],
    position_lots: 0,
    realized_pnl: 0,
    unrealized_pnl: 0,
  };
}

export function useStrategy4Dashboard(pollMs = 1000) {
  const [data, setData] = useState<DashboardSnapshot | null>(() => loadCachedSnapshot());
  const [loading, setLoading] = useState(() => loadCachedSnapshot() == null);
  const [error, setError] = useState<string | null>(null);
  const [serverOnline, setServerOnline] = useState(true);
  const completedClearPendingRef = useRef(false);
  const serverOnlineRef = useRef(true);
  const inFlightRef = useRef(false);

  const cacheSnapshot = useCallback((snap: DashboardSnapshot) => {
    try {
      sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snap));
    } catch {
      /* ignore */
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!serverOnlineRef.current || inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const snap = await fetchDashboard();
      const next =
        completedClearPendingRef.current && snap.completed_trades.length > 0
          ? { ...snap, completed_trades: [] }
          : snap;
      if (completedClearPendingRef.current && snap.completed_trades.length === 0) {
        completedClearPendingRef.current = false;
      }
      setData(next);
      cacheSnapshot(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, [cacheSnapshot]);

  useEffect(() => {
    let cancelled = false;
    async function pingHealth() {
      try {
        const res = await fetch(`${getApiBase()}/health`, { cache: "no-store" });
        const body = (await res.json().catch(() => ({}))) as { status?: string };
        const online = res.ok && body.status === "ok";
        if (cancelled) return;
        serverOnlineRef.current = online;
        setServerOnline(online);
        if (!online) {
          sessionStorage.removeItem(SNAPSHOT_KEY);
          setData((prev) => (prev ? stripTradeData(prev) : EMPTY_DASHBOARD));
        }
      } catch {
        if (cancelled) return;
        serverOnlineRef.current = false;
        setServerOnline(false);
        sessionStorage.removeItem(SNAPSHOT_KEY);
        setData((prev) => (prev ? stripTradeData(prev) : EMPTY_DASHBOARD));
      }
    }
    void pingHealth();
    const id = window.setInterval(() => void pingHealth(), HEALTH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!serverOnline) return;
    void refresh();
    const id = window.setInterval(() => void refresh(), pollMs);
    return () => window.clearInterval(id);
  }, [refresh, pollMs, serverOnline]);

  const clearCompleted = useCallback(async () => {
    completedClearPendingRef.current = true;
    setData((prev) => (prev ? { ...prev, completed_trades: [] } : prev));
    try {
      await apiClearCompleted();
    } finally {
      completedClearPendingRef.current = false;
    }
  }, []);

  const clearLogs = useCallback(async () => {
    setData((prev) => (prev ? { ...prev, logs: [] } : prev));
    try {
      await apiClearLogs();
    } catch {
      /* ignore */
    }
  }, []);

  return { data, loading, error, refresh, serverOnline, clearCompleted, clearLogs };
}
