import { getApiBase, getStoredToken } from "@/lib/auth";

export function isAngelTokenErrorText(s: string | null | undefined): boolean {
  if (!s || !s.trim()) return false;
  return /invalid\s*token|jwt\s*expired|token\s*expired|access\s*denied|ag8001|angel\s*one\s*not\s*configured|angel_jwt_token|not\s*configured/i.test(
    s,
  );
}

export type McxQuoteSignal = {
  market_open?: boolean;
  source?: string;
  error?: string | null;
  price?: number;
};

export function detectMcxQuotesTokenExpiry(quotes: McxQuoteSignal[]): boolean {
  if (!quotes.length) return false;
  if (quotes.some((q) => isAngelTokenErrorText(q.error))) return true;
  const openWithPrice = quotes.filter((q) => q.market_open && (q.price ?? 0) > 0);
  if (!openWithPrice.length) return false;
  return openWithPrice.every((q) => q.source !== "live");
}

export type SensexQuoteSignal = {
  sensex_market_open?: boolean;
  sensex_source?: string;
  sensex_error?: string | null;
  sensex_price?: number;
};

export function detectSensexTokenExpiry(snap: SensexQuoteSignal): boolean {
  if (isAngelTokenErrorText(snap.sensex_error)) return true;
  const open = Boolean(snap.sensex_market_open);
  const price = snap.sensex_price ?? 0;
  const source = (snap.sensex_source ?? "").toLowerCase();
  return open && price > 0 && source !== "live";
}

export type RefreshResult =
  | { ok: true; message?: string }
  | { ok: false; error?: string };

export async function refreshAngelSession(): Promise<RefreshResult> {
  let token = getStoredToken();
  if (!token) {
    try {
      const sessionRes = await fetch("/api/auth/session", { cache: "no-store", credentials: "same-origin" });
      const sessionData = (await sessionRes.json().catch(() => ({}))) as {
        authenticated?: boolean;
        access_token?: string;
      };
      if (sessionData.access_token) {
        const { setStoredToken } = await import("@/lib/auth");
        setStoredToken(sessionData.access_token);
        token = sessionData.access_token;
      }
    } catch {
      /* ignore */
    }
  }
  if (!token) {
    return { ok: false, error: "Login required before refreshing Angel session." };
  }
  try {
    const res = await fetch(`${getApiBase()}/angel/refresh-session`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      message?: string;
      error?: string;
    };
    if (res.status === 401 || res.status === 403) {
      return { ok: false, error: "Login required before refreshing Angel session." };
    }
    if (data.ok === true) {
      return {
        ok: true,
        message: typeof data.message === "string" ? data.message : "Angel session refreshed.",
      };
    }
    return {
      ok: false,
      error: typeof data.error === "string" ? data.error : `Request failed (HTTP ${res.status})`,
    };
  } catch {
    return { ok: false, error: "Network error while refreshing Angel session." };
  }
}
