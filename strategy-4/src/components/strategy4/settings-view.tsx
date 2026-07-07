"use client";

import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { CardTitle, FieldLabel, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { fetchSettings, saveSettings } from "@/lib/strategy4/api";
import { SETTINGS_HELP } from "@/lib/settings-help";
import { EMPTY_CONFIG, configFromApi, type MarketKey, type Strategy4Config } from "@/lib/strategy4/types";

const MARKETS: { value: MarketKey; label: string }[] = [
  { value: "CRUDE_OIL", label: "Crude Oil" },
  { value: "NATURAL_GAS", label: "Natural Gas" },
  { value: "SILVER_MICRO", label: "Silver Micro" },
];

const LOT_OPTIONS = [1, 2, 4, 5, 6, 10];

function numInput(v: number): string {
  if (!Number.isFinite(v) || v === 0) return "";
  return String(v);
}

function parseNum(raw: string): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

export function Strategy4SettingsView() {
  const [cfg, setCfg] = useState<Strategy4Config>(EMPTY_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetchSettings();
        if (!alive) return;
        setCfg(configFromApi(res.config));
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
    <div className="mx-auto max-w-2xl space-y-5 pb-10">
      <PageHeader
        title="Strategy Settings"
        subtitle="Single breakout with reverse entry — MCX Crude Oil / Natural Gas / Silver Micro"
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
        <p className="rounded-xl border border-[var(--danger-soft)] bg-[var(--danger-soft)] px-4 py-3 text-sm text-[var(--danger)]">{error}</p>
      ) : null}

      <PremiumCard className="!p-4">
        <CardTitle title="Instrument & Session" />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-2 sm:col-span-2">
            <FieldLabel label="Market" help={SETTINGS_HELP.market} />
            <select
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
              value={cfg.market}
              onChange={(e) => setCfg((c) => ({ ...c, market: e.target.value as MarketKey }))}
            >
              {MARKETS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <FloatingField
            id="start-time"
            label="Start Time (Reference Candle)"
            type="time"
            help={SETTINGS_HELP.startTime}
            value={cfg.startTime}
            onChange={(v) => setCfg((c) => ({ ...c, startTime: v }))}
          />
          <FloatingField
            id="end-time"
            label="End Time (MCX Session)"
            type="time"
            help={SETTINGS_HELP.endTime}
            value={cfg.endTime}
            onChange={(v) => setCfg((c) => ({ ...c, endTime: v }))}
          />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Breakout Parameters" />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-2">
            <FieldLabel label="Lot Size" help={SETTINGS_HELP.lotSize} />
            <select
              className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
              value={cfg.lotSize}
              onChange={(e) => setCfg((c) => ({ ...c, lotSize: Number(e.target.value) }))}
            >
              {LOT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <FloatingField
            id="breakout-distance"
            label="Breakout Distance (Points)"
            type="number"
            step="0.01"
            help={SETTINGS_HELP.breakoutDistance}
            placeholder="0.50"
            value={numInput(cfg.breakoutDistance)}
            onChange={(v) => setCfg((c) => ({ ...c, breakoutDistance: parseNum(v) }))}
          />
          <FloatingField
            id="take-profit"
            label="Take Profit (Points)"
            type="number"
            step="0.01"
            help={SETTINGS_HELP.takeProfit}
            placeholder="1.00"
            value={numInput(cfg.takeProfit)}
            onChange={(v) => setCfg((c) => ({ ...c, takeProfit: parseNum(v) }))}
          />
          <FloatingField
            id="stop-loss"
            label="Stop Loss (Points)"
            type="number"
            step="0.01"
            help={SETTINGS_HELP.stopLoss}
            placeholder="0.80"
            value={numInput(cfg.stopLoss)}
            onChange={(v) => setCfg((c) => ({ ...c, stopLoss: parseNum(v) }))}
          />
        </div>
        <p className="mt-3 text-xs leading-relaxed text-[var(--text-muted)]">
          Reference price = 1-min candle close at start time. First breakout (buy or sell) enters; opposite trigger is
          cancelled. One reverse trade allowed only after stop loss on the initial trade.
        </p>
      </PremiumCard>
    </div>
  );
}
