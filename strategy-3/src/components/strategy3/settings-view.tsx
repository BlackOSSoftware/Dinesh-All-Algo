"use client";

import { Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CardTitle, FieldLabel, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { fetchSettings, saveSettings } from "@/lib/strategy3/api";
import { SETTINGS_HELP } from "@/lib/settings-help";
import {
  DEFAULT_CONFIG,
  configFromApi,
  premiumTierLabel,
  windowTimes,
  type ExpiryInfo,
  type ProductType,
  type Strategy3Config,
} from "@/lib/strategy3/types";

function numInput(v: number): string {
  if (!Number.isFinite(v) || v === 0) return "";
  return String(v);
}

function parseNum(raw: string): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

export function Strategy3SettingsView() {
  const [cfg, setCfg] = useState<Strategy3Config>(DEFAULT_CONFIG);
  const [expiryInfo, setExpiryInfo] = useState<ExpiryInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const windows = useMemo(() => windowTimes(cfg), [cfg]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetchSettings();
        if (!alive) return;
        setCfg(configFromApi(res.config));
        if (res.expiry_info) setExpiryInfo(res.expiry_info as ExpiryInfo);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Load failed");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await saveSettings(cfg);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-[var(--text-muted)]">Loading settings…</p>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 pb-10">
      <PageHeader
        title="Strategy Settings"
        subtitle="SENSEX Expiry Day ITM Breakout — 10-minute candle windows"
        action={
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-60"
          >
            <Save className="h-4 w-4" />
            {saved ? "Saved" : saving ? "Saving…" : "Save"}
          </button>
        }
      />

      {error ? (
        <p className="rounded-xl border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </p>
      ) : null}

      <PremiumCard className="!p-4">
        <CardTitle title="Session Windows" subtitle="Next window only if previous trade exited via TP/SL" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField
            id="start-time"
            label="First Window Start"
            type="time"
            help={SETTINGS_HELP.startTime}
            value={cfg.startTime}
            onChange={(v) => setCfg((c) => ({ ...c, startTime: v }))}
          />
          <FloatingField
            id="window-count"
            label="Number of Windows"
            type="number"
            help={SETTINGS_HELP.windowCount}
            value={String(cfg.windowCount)}
            onChange={(v) => setCfg((c) => ({ ...c, windowCount: Math.max(1, Math.min(5, parseNum(v) || 1)) }))}
          />
          <FloatingField
            id="window-gap"
            label="Gap Between Windows (min)"
            type="number"
            help={SETTINGS_HELP.windowGapMinutes}
            value={String(cfg.windowGapMinutes)}
            onChange={(v) => setCfg((c) => ({ ...c, windowGapMinutes: Math.max(5, parseNum(v) || 10) }))}
          />
          <FloatingField
            id="candle-tf"
            label="Candle Timeframe (min)"
            type="number"
            help={SETTINGS_HELP.candleTimeframeMinutes}
            value={String(cfg.candleTimeframeMinutes)}
            onChange={(v) => setCfg((c) => ({ ...c, candleTimeframeMinutes: 10 }))}
            disabled
          />
        </div>
        <div className="mt-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm">
          <p className="font-medium text-[var(--text-secondary)]">Trade windows (10m candle close)</p>
          <p className="mt-1 tabular-nums text-[var(--text-primary)]">{windows.join(" → ")}</p>
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            Example: 14:35 → 14:45 → 14:55. If 14:35 trade is still open at 14:45, the 14:45 window is skipped.
          </p>
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Trade Parameters" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField
            id="target-pct"
            label="Target (%)"
            type="number"
            help={SETTINGS_HELP.targetPercent}
            value={numInput(cfg.targetPercent)}
            onChange={(v) => setCfg((c) => ({ ...c, targetPercent: parseNum(v) }))}
          />
          <FloatingField
            id="sl-pct"
            label="Stop Loss (%)"
            type="number"
            help={SETTINGS_HELP.stopLossPercent}
            value={numInput(cfg.stopLossPercent)}
            onChange={(v) => setCfg((c) => ({ ...c, stopLossPercent: parseNum(v) }))}
          />
          <FloatingField
            id="quantity"
            label="Quantity (lots)"
            type="number"
            help={SETTINGS_HELP.quantity}
            value={numInput(cfg.quantity)}
            onChange={(v) => setCfg((c) => ({ ...c, quantity: Math.max(1, parseNum(v) || 1) }))}
          />
          <label className="block space-y-2">
            <FieldLabel label="Product Type" help={SETTINGS_HELP.productType} />
            <select
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
              value={cfg.productType}
              onChange={(e) => setCfg((c) => ({ ...c, productType: e.target.value as ProductType }))}
            >
              <option value="MIS">MIS (Intraday)</option>
              <option value="NRML">NRML (Carry Forward)</option>
            </select>
          </label>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-xs text-[var(--text-muted)] sm:col-span-2">
            Base quantity stays the same as configured here. If one trade closes in loss, the next trade size multiplier doubles.
            If that trade also loses, the next one doubles again. After a non-loss trade, the multiplier resets back to 1x.
          </div>
          <label className="flex items-center gap-2 sm:col-span-2">
            <input
              type="checkbox"
              checked={cfg.expiryDayOnly}
              onChange={(e) => setCfg((c) => ({ ...c, expiryDayOnly: e.target.checked }))}
              className="h-4 w-4 rounded border-[var(--border-subtle)]"
            />
            <FieldLabel label="Run only on SENSEX expiry day" help={SETTINGS_HELP.expiryDayOnly} />
          </label>
          {cfg.expiryDayOnly ? (
            <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 sm:col-span-2">
              <p className="text-sm font-medium text-[var(--text-secondary)]">Auto-detected expiry</p>
              <p className="mt-1 text-sm text-[var(--text-primary)]">
                This week: {expiryInfo?.currentWeekExpiryLabel ?? "Loading…"}
              </p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                Next expiry: {expiryInfo?.nextExpiryLabel ?? "—"}
                {expiryInfo?.source ? ` · Source: ${expiryInfo.source.replaceAll("_", " ")}` : ""}
              </p>
              <p className="mt-2 text-xs text-[var(--text-muted)]">
                Expiry is read from BFO SENSEX option contracts (Angel scrip master). If Thursday is a holiday
                and expiry moves to Wednesday, it is picked up automatically — no manual selection needed.
              </p>
            </div>
          ) : null}
        </div>
      </PremiumCard>

      <PremiumCard className="!p-0 overflow-hidden">
        <div className="border-b border-[var(--border-subtle)] px-4 py-3">
          <CardTitle title="Premium Eligibility — Entry %" subtitle="Buy stop at Premium Close × (1 + Entry %)" />
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--surface-muted)]">
                <th className="px-4 py-2 font-medium">Premium Close</th>
                <th className="px-4 py-2 font-medium">
                  <FieldLabel label="Entry %" help={SETTINGS_HELP.entryPercent} />
                </th>
              </tr>
            </thead>
            <tbody>
              {cfg.premiumTiers.map((tier, index) => (
                <tr key={index} className="border-b border-[var(--border-subtle)]">
                  <td className="px-4 py-2">{premiumTierLabel(cfg.premiumTiers, index)}</td>
                  <td className="px-4 py-2">
                    <input
                      type="number"
                      min={0}
                      max={200}
                      step={1}
                      value={tier.entryPercent}
                      onChange={(e) => {
                        const val = parseNum(e.target.value);
                        setCfg((c) => ({
                          ...c,
                          premiumTiers: c.premiumTiers.map((t, i) =>
                            i === index ? { ...t, entryPercent: val } : t,
                          ),
                        }));
                      }}
                      className="w-24 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-3 py-1.5 text-sm tabular-nums outline-none focus:border-[var(--accent)]"
                    />
                    <span className="ml-1 text-[var(--text-muted)]">%</span>
                  </td>
                </tr>
              ))}
              <tr>
                <td className="px-4 py-2 text-[var(--danger)]">
                  {"\u003e"} {cfg.premiumTiers[cfg.premiumTiers.length - 1]?.maxPremium ?? 125} or ≤ 0
                </td>
                <td className="px-4 py-2 text-[var(--danger)]">No trade</td>
              </tr>
            </tbody>
          </table>
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Strike Selection" subtitle="Nearest ITM from 10m SENSEX reference close" />
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-[var(--text-secondary)]">
          <li>Call: highest strike below reference (e.g. ref 77,136 → 77,100 CE)</li>
          <li>Put: lowest strike above reference (e.g. ref 77,136 → 77,200 PE)</li>
          <li>CE and PE evaluated independently — both, one, or neither may qualify</li>
        </ul>
      </PremiumCard>
    </div>
  );
}
