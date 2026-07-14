/**
 * Display-only strategy math — mirrors sensex_trend_core / backtest planned levels.
 */

import { buildPlannedLevelsFromParams } from "@/lib/backtest-trend-analysis";

export type StrategyWorkflowPhase =
  | "WAITING_SESSION"
  | "WAITING_BASE"
  | "BASE_CAPTURED"
  | "WATCHING_TRIGGERS"
  | "CYCLE_OPEN"
  | "CORE_TP1"
  | "TP2_TRAIL"
  | "WAIT_REENTRY"
  | "SESSION_END";

export type CalculatedTradeType =
  | "Initial Call"
  | "Initial Put"
  | "Call Avg"
  | "Put Avg"
  | "Call Re-entry"
  | "Put Re-entry";

export type CalculatedTradeRow = {
  id: string;
  tradeType: CalculatedTradeType;
  entryLevel: number | null;
  lots: number;
  tp1: number | null;
  tp2Trail: number | null;
  stoploss: number | null;
  status: string;
  side: "CALL" | "PUT";
  editableLots: boolean;
};

export type StrategyLevels = {
  basePrice: number | null;
  upperTrigger: number | null;
  lowerTrigger: number | null;
  capturedCandleTime: string | null;
};

export type StrategyParams = {
  startTime: string;
  endTime: string;
  rangeGap: number;
  stopDistance: number;
  averagingGap: number;
  maxEntries: number;
  entryLots: number[];
  firstEntryTp1: number;
  avgTp1: number;
  tp2Trail: number;
  reEntryGap: number;
  reEntryEnabled: boolean;
  firstEntryEnabled: boolean;
  callEnabled: boolean;
  putEnabled: boolean;
};

export const STRATEGY_SPEC_DEFAULTS = {
  startTime: "09:15",
  endTime: "15:30",
  rangeGap: 191,
  stopDistance: 191,
  averagingGap: 45,
  maxEntries: 4,
  entryLots: [2, 1, 1, 1],
  firstEntryTp1: 70,
  avgTp1: 45,
  tp2Trail: 30,
  reEntryGap: 70,
  reEntryEnabled: true,
  firstEntryEnabled: true,
  callEnabled: true,
  putEnabled: true,
};

export function roundPx(n: number): number {
  return Math.round(n * 100) / 100;
}

export function fmtLevel(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function computeLevels(basePrice: number | null, rangeGap: number): StrategyLevels {
  if (basePrice == null || !Number.isFinite(basePrice) || basePrice <= 0) {
    return { basePrice: null, upperTrigger: null, lowerTrigger: null, capturedCandleTime: null };
  }
  return {
    basePrice: roundPx(basePrice),
    upperTrigger: roundPx(basePrice + rangeGap),
    lowerTrigger: roundPx(basePrice - rangeGap),
    capturedCandleTime: null,
  };
}

function mapPlannedType(type: string, side: string): CalculatedTradeType {
  if (type === "CALL_TRIGGER") return "Initial Call";
  if (type === "PUT_TRIGGER") return "Initial Put";
  if (type.startsWith("CALL_AVG")) return "Call Avg";
  if (type.startsWith("PUT_AVG")) return "Put Avg";
  if (side === "CALL") return "Call Re-entry";
  return "Put Re-entry";
}

export function buildCalculatedTradeRows(
  levels: StrategyLevels,
  params: StrategyParams,
  _adaptiveHigh: number | null,
  _adaptiveLow: number | null,
  liveIndex: number | null,
): CalculatedTradeRow[] {
  const { upperTrigger: upper, lowerTrigger: lower, basePrice: base } = levels;
  if (upper == null || lower == null || base == null) return [];

  const statusAt = (entry: number, side: "CALL" | "PUT") => {
    if (liveIndex == null) return "Pending";
    if (side === "CALL") return liveIndex >= entry ? "Trigger reached" : "Waiting";
    return liveIndex <= entry ? "Trigger reached" : "Waiting";
  };

  const planned = buildPlannedLevelsFromParams(base, {
    entryTrigger: params.rangeGap,
    stopDistance: params.stopDistance,
    initialLots: params.entryLots[0] ?? 2,
    addLots: params.entryLots[1] ?? 1,
    entryLots: params.entryLots,
    averagingGap: params.averagingGap,
    maxEntries: params.maxEntries,
    tp1Points: params.avgTp1,
    firstEntryTp1Points: params.firstEntryTp1,
    tp2Trail: params.tp2Trail,
    reEntryGap: params.reEntryGap,
    reEntryEnabled: params.reEntryEnabled,
  });

  const rows: CalculatedTradeRow[] = [];

  for (const pl of planned) {
    if (pl.type === "BASE") continue;

    if (pl.type === "REENTRY_RULE") {
      if (params.reEntryEnabled && params.callEnabled) {
        rows.push({
          id: "reentry-call",
          tradeType: "Call Re-entry",
          entryLevel: null,
          lots: params.entryLots[0] ?? 2,
          tp1: null,
          tp2Trail: params.tp2Trail,
          stoploss: null,
          status: `After TP2 · ADP high − ${params.reEntryGap}pt`,
          side: "CALL",
          editableLots: false,
        });
      }
      if (params.reEntryEnabled && params.putEnabled) {
        rows.push({
          id: "reentry-put",
          tradeType: "Put Re-entry",
          entryLevel: null,
          lots: params.entryLots[0] ?? 2,
          tp1: null,
          tp2Trail: params.tp2Trail,
          stoploss: null,
          status: `After TP2 · ADP low + ${params.reEntryGap}pt`,
          side: "PUT",
          editableLots: false,
        });
      }
      continue;
    }

    const side = pl.side === "PUT" ? "PUT" : "CALL";
    if (side === "CALL" && !params.callEnabled) continue;
    if (side === "PUT" && !params.putEnabled) continue;

    const isInitial = pl.type === "CALL_TRIGGER" || pl.type === "PUT_TRIGGER";
    let status = statusAt(pl.level, side);
    if (isInitial && !params.firstEntryEnabled) status = "First entry disabled";
    if (!isInitial) status = `Avg #${pl.type.split("_").pop()} · TP1 only`;

    rows.push({
      id: pl.type.toLowerCase(),
      tradeType: mapPlannedType(pl.type, pl.side),
      entryLevel: pl.level,
      lots: pl.lots,
      tp1: pl.tp1,
      tp2Trail: pl.tp2Trail,
      stoploss: pl.stopLoss,
      status,
      side,
      editableLots: false,
    });
  }

  return rows;
}

export function parseIstMinutes(hhmm: string): number | null {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm.trim());
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

export function nowIstMinutes(): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const h = parseInt(parts.find((p) => p.type === "hour")?.value ?? "0", 10);
  const min = parseInt(parts.find((p) => p.type === "minute")?.value ?? "0", 10);
  return h * 60 + min;
}

export type PositionProgress = "NONE" | "OPEN" | "POST_CORE_TP1";

export function inferPositionProgress(input: {
  activeLots: number;
  activeSide: "CALL" | "PUT" | "NONE" | "MIXED";
  sawCoreTp1Today: boolean;
  isFlat: boolean;
}): PositionProgress {
  if (input.activeSide !== "NONE" && input.activeSide !== "MIXED" && input.activeLots > 0) {
    if (input.sawCoreTp1Today) return "POST_CORE_TP1";
    return "OPEN";
  }
  if (input.isFlat && input.sawCoreTp1Today) return "POST_CORE_TP1";
  return "NONE";
}

export function deriveWorkflowPhase(input: {
  startTime: string;
  endTime: string;
  basePrice: number | null;
  liveIndex: number | null;
  upperTrigger: number | null;
  lowerTrigger: number | null;
  activeSide: "CALL" | "PUT" | "NONE" | "MIXED";
  positionProgress: PositionProgress;
  tp1Reached: boolean;
  waitReentry: boolean;
}): StrategyWorkflowPhase {
  const start = parseIstMinutes(input.startTime);
  const end = parseIstMinutes(input.endTime);
  const now = nowIstMinutes();

  if (start != null && now < start) return "WAITING_SESSION";
  if (input.basePrice == null) return "WAITING_BASE";
  if (end != null && now > end) return "SESSION_END";

  if (input.waitReentry) return "WAIT_REENTRY";

  if (input.activeSide !== "NONE" && input.activeSide !== "MIXED") {
    if (input.positionProgress === "POST_CORE_TP1" || input.tp1Reached) return "TP2_TRAIL";
    return "CYCLE_OPEN";
  }

  if (
    input.liveIndex != null &&
    input.upperTrigger != null &&
    input.lowerTrigger != null
  ) {
    return "WATCHING_TRIGGERS";
  }

  return "BASE_CAPTURED";
}

export const WORKFLOW_STEPS: { phase: StrategyWorkflowPhase; label: string }[] = [
  { phase: "WAITING_SESSION", label: "Session" },
  { phase: "WAITING_BASE", label: "Base" },
  { phase: "BASE_CAPTURED", label: "Base Ready" },
  { phase: "WATCHING_TRIGGERS", label: "Triggers" },
  { phase: "CYCLE_OPEN", label: "In Cycle" },
  { phase: "CORE_TP1", label: "Core TP1" },
  { phase: "TP2_TRAIL", label: "TP2 Trail" },
  { phase: "WAIT_REENTRY", label: "Re-entry" },
  { phase: "SESSION_END", label: "EOD" },
];
