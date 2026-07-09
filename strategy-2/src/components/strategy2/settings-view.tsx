"use client";

import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { CardTitle, FieldLabel, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { fetchSettings, saveSettings } from "@/lib/strategy2/api";
import { SETTINGS_HELP } from "@/lib/settings-help";
import { ExpirySideSelectors } from "@/components/strategy2/expiry-side-selectors";
import { EMPTY_CONFIG, configFromApi, type MarketKey, type Strategy2Config } from "@/lib/strategy2/types";

const MARKETS: { value: MarketKey; label: string }[] = [
  { value: "CRUDE_OIL", label: "Crude Oil" },
  { value: "CRUDE_OIL_MINI", label: "Crude Oil Mini" },
  { value: "CRUDE_OIL_MEGA", label: "Crude Oil Mega" },
  { value: "NATURAL_GAS", label: "Natural Gas" },
  { value: "NATURAL_GAS_MINI", label: "Natural Gas Mini" },
  { value: "NATURAL_GAS_MEGA", label: "Natural Gas Mega" },
  { value: "SILVER_MICRO", label: "Silver Micro" },
  { value: "SILVER_MINI", label: "Silver Mini" },
];

function numInput(v: number): string {
  if (!Number.isFinite(v) || v === 0) return "";
  return String(v);
}

function parseNum(raw: string): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

export function Strategy2SettingsView() {
  const [cfg, setCfg] = useState<Strategy2Config>(EMPTY_CONFIG);
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
        subtitle="MCX grid strategy — configure algo and grid parameters"
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
        <CardTitle title="Algo Settings" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField
            id="start-time"
            label="Start Time"
            type="time"
            help={SETTINGS_HELP.startTime}
            value={cfg.startTime}
            onChange={(v) => setCfg((c) => ({ ...c, startTime: v }))}
          />
          <FloatingField
            id="end-time"
            label="End Time (MCX Market)"
            type="time"
            help={SETTINGS_HELP.endTime}
            value={cfg.endTime}
            onChange={(v) => setCfg((c) => ({ ...c, endTime: v }))}
          />
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
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Strategy Settings" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField
            id="ref-price"
            label="Reference Price"
            type="number"
            help={SETTINGS_HELP.referencePrice}
            placeholder=""
            value={numInput(cfg.referencePrice)}
            onChange={(v) => setCfg((c) => ({ ...c, referencePrice: parseNum(v) }))}
          />
          <FloatingField
            id="initial-lots"
            label="Initial Lots"
            type="number"
            help={SETTINGS_HELP.initialLots}
            placeholder=""
            value={numInput(cfg.initialLots)}
            onChange={(v) => setCfg((c) => ({ ...c, initialLots: parseNum(v) }))}
          />
          <FloatingField
            id="grid-gap"
            label="Grid Gap (Points)"
            type="number"
            help={SETTINGS_HELP.gridGap}
            placeholder=""
            value={numInput(cfg.gridGap)}
            onChange={(v) => setCfg((c) => ({ ...c, gridGap: parseNum(v) }))}
          />
          <FloatingField
            id="levels-above"
            label="Grid Levels Above"
            type="number"
            help={SETTINGS_HELP.gridLevelsAbove}
            placeholder=""
            value={numInput(cfg.gridLevelsAbove)}
            onChange={(v) => setCfg((c) => ({ ...c, gridLevelsAbove: parseNum(v) }))}
          />
          <FloatingField
            id="levels-below"
            label="Grid Levels Below"
            type="number"
            help={SETTINGS_HELP.gridLevelsBelow}
            placeholder=""
            value={numInput(cfg.gridLevelsBelow)}
            onChange={(v) => setCfg((c) => ({ ...c, gridLevelsBelow: parseNum(v) }))}
          />
          <FloatingField
            id="lots-per-grid"
            label="Lots Per Grid"
            type="number"
            help={SETTINGS_HELP.lotsPerGrid}
            placeholder=""
            value={numInput(cfg.lotsPerGrid)}
            onChange={(v) => setCfg((c) => ({ ...c, lotsPerGrid: parseNum(v) }))}
          />
        </div>

        <ExpirySideSelectors
          market={cfg.market}
          cfg={cfg}
          onChange={(patch) => setCfg((c) => ({ ...c, ...patch }))}
        />
      </PremiumCard>
    </div>
  );
}
