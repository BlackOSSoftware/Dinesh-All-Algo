"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useState } from "react";
import { cn } from "@/components/ui";
import { refreshAngelSession } from "@/lib/angel-session";

type AngelTokenRefreshBannerProps = {
  show: boolean;
};

export function AngelTokenRefreshBanner({ show }: AngelTokenRefreshBannerProps) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const runRefresh = useCallback(async () => {
    setBusy(true);
    setFeedback(null);
    try {
      const result = await refreshAngelSession();
      if (result.ok) {
        setFeedback(result.message ?? "Angel session refreshed. Reloading…");
        window.location.reload();
        return;
      }
      setFeedback(result.error ?? "Token refresh failed.");
    } catch {
      setFeedback("Network error while refreshing Angel session.");
    } finally {
      setBusy(false);
    }
  }, []);

  if (!show) return null;

  return (
    <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-amber-900 dark:text-amber-100">
          Angel SmartAPI token expired or invalid. Generate a new token to restore live prices.
        </p>
        <button
          type="button"
          onClick={() => void runRefresh()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          <RefreshCw className={cn("h-4 w-4", busy && "animate-spin")} />
          {busy ? "Generating token…" : "Generate Token"}
        </button>
      </div>
      {feedback ? <p className="mt-2 text-xs text-[var(--text-muted)]">{feedback}</p> : null}
    </div>
  );
}
