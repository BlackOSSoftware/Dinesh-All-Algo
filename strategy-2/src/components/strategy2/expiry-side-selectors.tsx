"use client";

import { useEffect, useState } from "react";
import { FieldLabel } from "@/components/trader/ui/primitives";
import { fetchMcxExpiries } from "@/lib/strategy2/api";
import { SETTINGS_HELP } from "@/lib/settings-help";
import {
  buySellFromExpirySlots,
  defaultExpirySlots,
  inferExpirySlots,
  resolveInvertGridForDate,
  type MarketKey,
  type McxExpiryOption,
  type Strategy2Config,
} from "@/lib/strategy2/types";

function expiryOptionLabel(row: McxExpiryOption): string {
  return `${row.tradingsymbol} · ${row.expiryLabel}`;
}

type Side = "buy" | "sell";

type Props = {
  market: MarketKey;
  cfg: Strategy2Config;
  onChange: (patch: Partial<Strategy2Config>) => void;
  includeExpired?: boolean;
  showActiveBanner?: boolean;
  hint?: string;
};

function SideToggle({
  value,
  onChange,
}: {
  value: Side;
  onChange: (side: Side) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {(["buy", "sell"] as const).map((side) => (
        <button
          key={side}
          type="button"
          onClick={() => onChange(side)}
          className={`rounded-xl border px-3 py-2.5 text-center text-sm font-medium transition ${
            value === side
              ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
              : "border-[var(--border-subtle)] bg-[var(--surface-muted)] text-[var(--text-primary)] hover:border-[var(--accent)]"
          }`}
        >
          {side === "buy" ? "Buy Side" : "Short Sell"}
        </button>
      ))}
    </div>
  );
}

function MonthSlot({
  title,
  help,
  expiry,
  side,
  expiries,
  onExpiryChange,
  onSideChange,
}: {
  title: string;
  help: string;
  expiry: string;
  side: Side;
  expiries: McxExpiryOption[];
  onExpiryChange: (expiry: string) => void;
  onSideChange: (side: Side) => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)]/40 p-4">
      <p className="text-sm font-medium text-[var(--text-secondary)]">
        <FieldLabel label={title} help={help} />
      </p>
      <label className="block space-y-2">
        <span className="text-xs text-[var(--text-muted)]">Contract expiry</span>
        <select
          className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
          value={expiry}
          disabled={!expiries.length}
          onChange={(e) => onExpiryChange(e.target.value)}
        >
          {!expiries.length ? <option value="">No expiries found</option> : null}
          {expiries.map((row) => (
            <option key={row.expiry} value={row.expiry}>
              {expiryOptionLabel(row)}
            </option>
          ))}
        </select>
      </label>
      <div className="space-y-2">
        <FieldLabel label="This month runs as" help={help} />
        <SideToggle value={side} onChange={onSideChange} />
      </div>
    </div>
  );
}

export function ExpirySideSelectors({
  market,
  cfg,
  onChange,
  includeExpired = false,
  showActiveBanner = true,
  hint,
}: Props) {
  const [expiries, setExpiries] = useState<McxExpiryOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slots = inferExpirySlots(cfg, expiries);
  const month1 = cfg.expiryMonth1 || slots.expiryMonth1;
  const month2 = cfg.expiryMonth2 || slots.expiryMonth2;
  const side1 = cfg.expiryMonth1Side === "sell" ? "sell" : "buy";
  const side2 = cfg.expiryMonth2Side === "buy" ? "buy" : "sell";

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    void fetchMcxExpiries(market, includeExpired)
      .then((rows) => {
        if (!alive) return;
        setExpiries(rows);
        if (!rows.length) {
          onChange({
            buySideExpiry: "",
            sellSideExpiry: "",
            expiryMonth1: "",
            expiryMonth2: "",
          });
          return;
        }
        const m1Valid = rows.some((r) => r.expiry === month1);
        const m2Valid = rows.some((r) => r.expiry === month2);
        if (!month1 || !month2 || !m1Valid || !m2Valid) {
          const defaults = defaultExpirySlots(rows);
          const inferred = inferExpirySlots(cfg, rows);
          const nextM1 = m1Valid ? month1 : inferred.expiryMonth1 || defaults.expiryMonth1;
          const nextM2 = m2Valid ? month2 : inferred.expiryMonth2 || defaults.expiryMonth2;
          const nextS1 = side1;
          const nextS2 = side2;
          onChange({
            expiryMonth1: nextM1,
            expiryMonth1Side: nextS1,
            expiryMonth2: nextM2,
            expiryMonth2Side: nextS2,
            ...buySellFromExpirySlots(nextM1, nextS1, nextM2, nextS2),
          });
        }
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "Failed to load expiries");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh when market or includeExpired changes
  }, [market, includeExpired]);

  function applySlots(m1: string, s1: Side, m2: string, s2: Side) {
    onChange({
      expiryMonth1: m1,
      expiryMonth1Side: s1,
      expiryMonth2: m2,
      expiryMonth2Side: s2,
      ...buySellFromExpirySlots(m1, s1, m2, s2),
    });
  }

  const activeInvert = resolveInvertGridForDate(cfg, new Date());
  const buyRow = expiries.find((r) => r.expiry === cfg.buySideExpiry);
  const sellRow = expiries.find((r) => r.expiry === cfg.sellSideExpiry);

  return (
    <div className="mt-4 border-t border-[var(--border-subtle)] pt-4">
      <p className="mb-3 text-sm font-medium text-[var(--text-secondary)]">
        <FieldLabel label="Contract Expiry Grid" help={SETTINGS_HELP.expiryMonth1} />
      </p>
      {error ? (
        <p className="mb-3 rounded-xl border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-3 py-2 text-xs text-[var(--danger)]">
          {error}
          {error.toLowerCase().includes("jwt") || error.toLowerCase().includes("token") ? (
            <span className="mt-1 block">Open the dashboard and click Generate Token, then reload this page.</span>
          ) : null}
        </p>
      ) : null}
      {!loading && !error && !expiries.length ? (
        <p className="mb-3 text-xs text-[var(--text-muted)]">
          No expiries loaded. Check Angel login (Generate Token) and that the backend is running.
        </p>
      ) : null}
      {loading && !expiries.length ? (
        <p className="mb-3 text-xs text-[var(--text-muted)]">Loading contract expiries…</p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <MonthSlot
          title="Month 1 — Expiry"
          help={SETTINGS_HELP.expiryMonth1}
          expiry={month1}
          side={side1}
          expiries={expiries}
          onExpiryChange={(expiry) => applySlots(expiry, side1, month2, side2)}
          onSideChange={(side) => applySlots(month1, side, month2, side2)}
        />
        <MonthSlot
          title="Month 2 — Expiry"
          help={SETTINGS_HELP.expiryMonth2}
          expiry={month2}
          side={side2}
          expiries={expiries}
          onExpiryChange={(expiry) => applySlots(month1, side1, expiry, side2)}
          onSideChange={(side) => applySlots(month1, side1, month2, side)}
        />
      </div>

      {hint ? <p className="mt-3 text-xs text-[var(--text-muted)]">{hint}</p> : null}
      {showActiveBanner ? (
        <div
          className={`mt-3 rounded-xl border px-4 py-3 text-sm ${
            activeInvert
              ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
              : "border-[var(--border-subtle)] bg-[var(--surface-muted)] text-[var(--text-primary)]"
          }`}
        >
          <span className="font-medium">
            Active now: {activeInvert ? "Short Sell" : "Buy Side"}
          </span>
          <span className="mt-1 block text-xs opacity-80">
            {activeInvert
              ? sellRow
                ? `${sellRow.tradingsymbol} · ${sellRow.expiryLabel}`
                : "No Short Sell contract selected"
              : buyRow
                ? `${buyRow.tradingsymbol} · ${buyRow.expiryLabel}`
                : "No Buy Side contract selected"}
          </span>
        </div>
      ) : null}
    </div>
  );
}
