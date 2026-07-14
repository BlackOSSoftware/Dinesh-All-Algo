"use client";

import { Save } from "lucide-react";
import { useState } from "react";

import { useTradingDashboard } from "@/components/trader/trading-dashboard-context";
import { CardTitle, FieldLabel, FloatingField, PageHeader, PremiumCard } from "@/components/trader/ui/primitives";
import { cn } from "@/components/ui";
import { normalizeEntryLots } from "@/lib/backtest-trend-analysis";
import { SETTINGS_HELP } from "@/lib/settings-help";

function displayField(v: number | null | undefined, bootDone: boolean): string {
  if (!bootDone) return "";
  if (v == null || !Number.isFinite(v) || v === 0) return "";
  return String(v);
}

function displayTime(v: string, bootDone: boolean): string {
  if (!bootDone) return "";
  return v || "";
}

function patchInt(v: string, set: (n: number) => void, min = 1) {
  if (v === "") {
    set(0);
    return;
  }
  const n = parseInt(v, 10);
  if (!Number.isFinite(n)) return;
  if (min > 0 && n < min) return;
  set(n);
}

function ToggleRow({
  label,
  help,
  value,
  onChange,
}: {
  label: string;
  help?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-[var(--text-muted)]">
        <FieldLabel label={label} help={help} />
      </p>
      <div className="flex max-w-xs rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-0.5">
        {([true, false] as const).map((enabled) => (
          <button
            key={String(enabled)}
            type="button"
            onClick={() => onChange(enabled)}
            className={cn(
              "flex-1 rounded-md py-2 text-xs font-medium transition",
              value === enabled
                ? "bg-[var(--surface-elevated)] text-[var(--accent)] shadow-sm"
                : "text-[var(--text-muted)]",
            )}
          >
            {enabled ? "Yes" : "No"}
          </button>
        ))}
      </div>
    </div>
  );
}

export function StrategyView() {
  const d = useTradingDashboard();
  const [saveFlash, setSaveFlash] = useState(false);

  async function handleSave() {
    await d.pushSettingsToServer();
    setSaveFlash(true);
    window.setTimeout(() => setSaveFlash(false), 1200);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4 pb-10">
      <PageHeader
        title="Settings"
        subtitle="SENSEX Adaptive Trend Averaging — hover the i icon on any field for help"
        action={
          <button
            type="button"
            onClick={() => void handleSave()}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition hover:opacity-90"
          >
            <Save className="h-4 w-4" />
            {saveFlash ? "Saved" : "Save"}
          </button>
        }
      />

      <PremiumCard className="!p-4">
        <CardTitle title="Session" subtitle="When the algo is allowed to run" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField id="set-start" label="Start Time (Base Candle)" help={SETTINGS_HELP.startTime} type="time" value={displayTime(d.startTime, d.bootDone)} onChange={(v) => d.setStartTime(v)} placeholder="09:15" />
          <FloatingField id="set-end" label="End Time" help={SETTINGS_HELP.endTime} type="time" value={displayTime(d.endTime, d.bootDone)} onChange={(v) => d.setEndTime(v)} placeholder="15:30" />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Entry & Strike" subtitle="Trigger distance and option selection" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField id="set-entry-trigger" label="Entry Trigger Points" help={SETTINGS_HELP.entryGap} type="number" value={displayField(d.entryGap, d.bootDone)} placeholder="191" onChange={(v) => patchInt(v, d.setEntryGap)} />
          <FloatingField id="set-strike-offset" label="Strike Offset" help={SETTINGS_HELP.strikeOffset} type="number" value={displayField(d.strikeOffset, d.bootDone)} placeholder="200" onChange={(v) => patchInt(v, d.setStrikeOffset, 50)} />
          <FloatingField id="set-stop-dist" label="Stop Distance (Index)" help={SETTINGS_HELP.stopDistance} type="number" value={displayField(d.stopDistance, d.bootDone)} placeholder="191" onChange={(v) => patchInt(v, d.setStopDistance)} />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Lots & Averaging" subtitle="Position sizing and scale-in rules" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField id="set-max-entries" label="Maximum Entries" help={SETTINGS_HELP.numEntries} type="number" value={displayField(d.numEntries, d.bootDone)} placeholder="4" onChange={(v) => patchInt(v, (n) => { d.setNumEntries(n); d.setEntryLots(normalizeEntryLots(d.entryLots, n, d.entryLots[0] ?? d.initialLots, d.entryLots[1] ?? d.addLots)); })} />
          {normalizeEntryLots(d.entryLots, d.numEntries, d.initialLots, d.addLots).map((lots, i) => (
            <FloatingField
              key={i}
              id={`set-entry-lots-${i}`}
              label={`Entry ${i + 1} Lots`}
              help={SETTINGS_HELP.entryLots}
              type="number"
              value={displayField(lots, d.bootDone)}
              placeholder={i === 0 ? "2" : "1"}
              onChange={(v) => {
                patchInt(v, (n) => {
                  const next = [...normalizeEntryLots(d.entryLots, d.numEntries, d.initialLots, d.addLots)];
                  next[i] = n;
                  const normalized = normalizeEntryLots(next, d.numEntries);
                  d.setEntryLots(normalized);
                  if (i === 0) d.setInitialLots(n);
                  if (i === 1) d.setAddLots(n);
                });
              }}
            />
          ))}
          <FloatingField id="set-avg-gap" label="Averaging Gap" help={SETTINGS_HELP.addGap} type="number" value={displayField(d.addGap, d.bootDone)} placeholder="45" onChange={(v) => patchInt(v, d.setAddGap)} />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Targets" subtitle="Take-profit and trailing exit levels" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField id="set-first-tp1" label="First Entry TP1" help={SETTINGS_HELP.firstEntryTp1} type="number" value={displayField(d.firstEntryTp1Pts, d.bootDone)} placeholder="70" onChange={(v) => patchInt(v, d.setFirstEntryTp1Pts)} />
          <FloatingField id="set-tp1-pts" label="Averaging TP1" help={SETTINGS_HELP.target1Pts} type="number" value={displayField(d.target1Pts, d.bootDone)} placeholder="45" onChange={(v) => patchInt(v, d.setTarget1Pts)} />
          <FloatingField id="set-tp2-trail" label="TP2 Trail Distance" help={SETTINGS_HELP.tp2Trail} type="number" value={displayField(d.tp2TrailPoints, d.bootDone)} placeholder="30" onChange={(v) => patchInt(v, d.setTp2TrailPoints)} />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Re-entry & Risk" subtitle="Second-chance entries and forced exit" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FloatingField id="set-reentry-gap" label="Re-entry Gap" help={SETTINGS_HELP.reEntryGap} type="number" value={displayField(d.reEntryGap, d.bootDone)} placeholder="70" onChange={(v) => patchInt(v, d.setReEntryGap)} />
          <FloatingField id="set-auto-sq" label="Auto Square-Off Time" help={SETTINGS_HELP.autoSquareOff} type="time" value={displayTime(d.autoSquareOffTime, d.bootDone)} onChange={(v) => d.setAutoSquareOffTime(v)} />
        </div>
      </PremiumCard>

      <PremiumCard className="!p-4">
        <CardTitle title="Sides & Re-entry" subtitle="Direction filters and cycle limits" />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-medium text-[var(--text-muted)]">
              <FieldLabel label="Trade Direction" help={SETTINGS_HELP.tradeDirection} />
            </p>
            <div className="flex rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-0.5">
              {(["BOTH", "CALL_ONLY", "PUT_ONLY"] as const).map((dir) => (
                <button key={dir} type="button" onClick={() => d.setTradeDirection(dir)} className={cn("flex-1 rounded-md py-2 text-xs font-medium", d.tradeDirection === dir ? "bg-[var(--surface-elevated)] text-[var(--accent)] shadow-sm" : "text-[var(--text-muted)]")}>
                  {dir === "BOTH" ? "Both" : dir === "CALL_ONLY" ? "Call Only" : "Put Only"}
                </button>
              ))}
            </div>
          </div>
          <ToggleRow label="Enable Call Side" help={SETTINGS_HELP.callEnabled} value={d.callEnabled} onChange={d.setCallEnabled} />
          <ToggleRow label="Enable Put Side" help={SETTINGS_HELP.putEnabled} value={d.putEnabled} onChange={d.setPutEnabled} />
          <ToggleRow label="Enable Re-entry" help={SETTINGS_HELP.reEntryEnabled} value={d.reEntryEnabled} onChange={d.setReEntryEnabled} />
          <ToggleRow label="First Entry" help={SETTINGS_HELP.firstEntryEnabled} value={d.firstEntryEnabled} onChange={d.setFirstEntryEnabled} />
          <FloatingField id="set-max-reentry" label="Max Re-entries / Day (0 = unlimited)" help={SETTINGS_HELP.maxReEntries} type="number" value={displayField(d.maxReEntries, d.bootDone)} placeholder="3" onChange={(v) => patchInt(v, d.setMaxReEntries, 0)} />
        </div>
      </PremiumCard>
    </div>
  );
}
