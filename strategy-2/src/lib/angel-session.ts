import { getApiBase, getStoredToken } from "@/lib/auth";

export function isAngelTokenErrorText(s: string | null | undefined): boolean {
  if (!s || !s.trim()) return false;
  // Rate-limit rejections are transient and NOT a token problem.
  if (/access\s*rate|exceeding|rate\s*limit/i.test(s)) return false;
  return /invalid\s*token|jwt\s*expired|token\s*expired|access\s*denied|ag8001|angel\s*one\s*not\s*configured|angel_jwt_token|not\s*configured|quote\s*unavailable|regenerate\s*token/i.test(
    s,
  );
}

export type McxQuoteSignal = {
  market_open?: boolean;
  source?: string;
  error?: string | null;
  price?: number;
};

function istPartsNow() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const weekday = parts.find((p) => p.type === "weekday")?.value ?? "";
  let hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  if (hour === 24) hour = 0;
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  return { weekday, hour, minute };
}

/** BSE cash session 09:15–15:30 IST weekdays. */
function isBseSessionOpenNow(): boolean {
  const { weekday, hour, minute } = istPartsNow();
  if (weekday === "Sat" || weekday === "Sun") return false;
  const totalMinutes = hour * 60 + minute;
  return totalMinutes >= 9 * 60 + 15 && totalMinutes <= 15 * 60 + 30;
}

/** MCX window used by strategies 2/4 (09:00–23:30 IST weekdays). */
function isMcxSessionOpenNow(): boolean {
  const { weekday, hour, minute } = istPartsNow();
  if (weekday === "Sat" || weekday === "Sun") return false;
  const totalMinutes = hour * 60 + minute;
  return totalMinutes >= 9 * 60 && totalMinutes <= 23 * 60 + 30;
}

export function detectMcxQuotesTokenExpiry(quotes: McxQuoteSignal[]): boolean {
  if (!quotes.length) return false;
  if (quotes.some((q) => isAngelTokenErrorText(q.error))) return true;
  if (!isMcxSessionOpenNow()) return false;
  const pricedQuotes = quotes.filter((q) => (q.price ?? 0) > 0);
  if (!pricedQuotes.length) return false;
  return pricedQuotes.every((q) => (q.source ?? "").toLowerCase() !== "live");
}

export type SensexQuoteSignal = {
  sensex_market_open?: boolean;
  sensex_source?: string;
  sensex_error?: string | null;
  sensex_price?: number;
};

export function detectSensexTokenExpiry(snap: SensexQuoteSignal): boolean {
  if (isAngelTokenErrorText(snap.sensex_error)) return true;
  if (!isBseSessionOpenNow()) return false;
  const price = snap.sensex_price ?? 0;
  const source = (snap.sensex_source ?? "").toLowerCase();
  return price > 0 && source !== "live";
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
      stderr_tail?: string;
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
    const primary =
      typeof data.error === "string" && data.error.trim()
        ? data.error.trim()
        : `Request failed (HTTP ${res.status})`;
    const tail =
      typeof data.stderr_tail === "string" && data.stderr_tail.trim() && !primary.includes(data.stderr_tail.trim())
        ? ` — ${data.stderr_tail.trim().slice(-500)}`
        : "";
    return { ok: false, error: `${primary}${tail}` };
  } catch {
    return { ok: false, error: "Network error while refreshing Angel session." };
  }
}
