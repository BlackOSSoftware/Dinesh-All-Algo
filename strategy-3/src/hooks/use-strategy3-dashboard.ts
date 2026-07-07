"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiBase } from "@/lib/auth";
import {
  clearCompletedTrades as apiClearCompleted,
  clearTradingLogs as apiClearLogs,
  fetchDashboard,
} from "@/lib/strategy3/api";
import { EMPTY_DASHBOARD, type DashboardSnapshot } from "@/lib/strategy3/types";

const SNAPSHOT_KEY = "strategy3_dashboard_snapshot";
const HEALTH_MS = 3000;
const POLL_MS = 2500;

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
    realized_pnl: 0,
    unrealized_pnl: 0,
  };
}

export function useStrategy3Dashboard() {
  const [snap, setSnap] = useState<DashboardSnapshot | null>(() => loadCachedSnapshot());
  const [loading, setLoading] = useState(() => loadCachedSnapshot() == null);
  const [error, setError] = useState<string | null>(null);
  const [serverOnline, setServerOnline] = useState(true);
  const completedClearPendingRef = useRef(false);
  const serverOnlineRef = useRef(true);

  const cacheSnapshot = useCallback((data: DashboardSnapshot) => {
    try {
      sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(data));
    } catch {
      /* ignore */
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!serverOnlineRef.current) return;
    try {
      const data = await fetchDashboard();
      const next =
        completedClearPendingRef.current && data.completed_trades.length > 0
          ? { ...data, completed_trades: [] }
          : data;
      if (completedClearPendingRef.current && data.completed_trades.length === 0) {
        completedClearPendingRef.current = false;
      }
      setSnap(next);
      cacheSnapshot(next);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Dashboard load failed");
    } finally {
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
          setSnap((prev) => (prev ? stripTradeData(prev) : EMPTY_DASHBOARD));
        }
      } catch {
        if (cancelled) return;
        serverOnlineRef.current = false;
        setServerOnline(false);
        sessionStorage.removeItem(SNAPSHOT_KEY);
        setSnap((prev) => (prev ? stripTradeData(prev) : EMPTY_DASHBOARD));
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
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh, serverOnline]);

  const clearCompleted = useCallback(async () => {
    completedClearPendingRef.current = true;
    setSnap((prev) => (prev ? { ...prev, completed_trades: [] } : prev));
    try {
      await apiClearCompleted();
    } finally {
      completedClearPendingRef.current = false;
    }
  }, []);

  const clearLogs = useCallback(async () => {
    setSnap((prev) => (prev ? { ...prev, logs: [] } : prev));
    try {
      await apiClearLogs();
    } catch {
      /* ignore */
    }
  }, []);

  return { snap, loading, error, refresh, serverOnline, clearCompleted, clearLogs };
}
