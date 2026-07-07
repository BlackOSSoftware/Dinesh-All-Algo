"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type Snapshot = Record<string, unknown> | null;

const SnapshotContext = createContext<{
  snapshot: Snapshot;
  reload: () => Promise<void>;
} | null>(null);

export function SnapshotProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<Snapshot>(null);
  const snapshotSigRef = useRef("");

  const reload = useCallback(async () => {
    try {
      const res = await fetch("/api/snapshot", { cache: "no-store", credentials: "same-origin" });
      if (!res.ok) return;
      const next = (await res.json()) as Snapshot;
      const sig = JSON.stringify(next);
      if (sig !== snapshotSigRef.current) {
        snapshotSigRef.current = sig;
        setSnapshot(next);
      }
    } catch {
      /* dashboard polls its own endpoints */
    }
  }, []);

  useEffect(() => {
    const first = window.setTimeout(() => void reload(), 0);
    const id = window.setInterval(() => void reload(), 15000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [reload]);

  return <SnapshotContext.Provider value={{ snapshot, reload }}>{children}</SnapshotContext.Provider>;
}

export function useSnapshot() {
  const ctx = useContext(SnapshotContext);
  if (!ctx) {
    return { snapshot: null, reload: async () => {} };
  }
  return ctx;
}
