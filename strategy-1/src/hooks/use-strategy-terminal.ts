"use client";

import { useEffect, useMemo, useRef } from "react";

import { useTradingDashboard } from "@/components/trader/trading-dashboard-context";
import { normalizeEntryLots } from "@/lib/backtest-trend-analysis";
import {
  buildCalculatedTradeRows,
  computeLevels,
  deriveWorkflowPhase,
  inferPositionProgress,
  roundPx,
  STRATEGY_SPEC_DEFAULTS,
  type CalculatedTradeRow,
  type StrategyLevels,
  type StrategyParams,
  type StrategyWorkflowPhase,
} from "@/lib/strategy-reference";

function activeSideFromTrades(trades: { side: string }[]): "CALL" | "PUT" | "NONE" | "MIXED" {
  const hasCall = trades.some((t) => /call|ce/i.test(t.side));
  const hasPut = trades.some((t) => /put|pe/i.test(t.side));
  if (hasCall && hasPut) return "MIXED";
  if (hasCall) return "CALL";
  if (hasPut) return "PUT";
  return "NONE";
}

function sawCoreTp1Today(logs: { message: string | null; action?: string | null }[]): boolean {
  return logs.some((l) => {
    const text = `${l.action ?? ""} ${l.message ?? ""}`.toLowerCase();
    return /t1 partial|partial closed|tp1|sensex_t1_done/i.test(text);
  });
}

function waitReentryFromLogs(logs: { message: string | null; action?: string | null }[]): boolean {
  return logs.some((l) => {
    const text = `${l.action ?? ""} ${l.message ?? ""}`.toLowerCase();
    return /wait_reentry|re.?entry|tp2_trail/i.test(text);
  });
}

export function useStrategyTerminal() {
  const d = useTradingDashboard();
  const baseCapturedRef = useRef(false);

  const liveIndex = useMemo(() => {
    const row = d.pickAngelQuoteRow(d.angel?.fetched);
    return d.quotePriceFromRow(row) ?? d.displayReferencePrice;
  }, [d]);

  const basePrice = d.effectiveBase != null && d.effectiveBase > 0 ? d.effectiveBase : null;

  const params: StrategyParams = useMemo(() => {
    const entryLots = normalizeEntryLots(
      d.entryLots,
      d.numEntries,
      d.initialLots,
      d.addLots,
    );
    return {
      startTime: d.startTime || STRATEGY_SPEC_DEFAULTS.startTime,
      endTime: d.endTime || STRATEGY_SPEC_DEFAULTS.endTime,
      rangeGap: d.entryGap || STRATEGY_SPEC_DEFAULTS.rangeGap,
      stopDistance: d.stopDistance || STRATEGY_SPEC_DEFAULTS.stopDistance,
      averagingGap: d.addGap || STRATEGY_SPEC_DEFAULTS.averagingGap,
      maxEntries: d.numEntries || STRATEGY_SPEC_DEFAULTS.maxEntries,
      entryLots,
      firstEntryTp1: d.firstEntryTp1Pts || STRATEGY_SPEC_DEFAULTS.firstEntryTp1,
      avgTp1: d.target1Pts || STRATEGY_SPEC_DEFAULTS.avgTp1,
      tp2Trail: d.tp2TrailPoints || STRATEGY_SPEC_DEFAULTS.tp2Trail,
      reEntryGap: d.reEntryGap || STRATEGY_SPEC_DEFAULTS.reEntryGap,
      reEntryEnabled: d.reEntryEnabled,
      firstEntryEnabled: d.firstEntryEnabled,
      callEnabled: d.callEnabled,
      putEnabled: d.putEnabled,
    };
  }, [d]);

  const levels: StrategyLevels = useMemo(() => {
    const l = computeLevels(basePrice, params.rangeGap);
    const candleTime =
      d.startBar?.candle_time ??
      (basePrice != null ? d.startBar?.start_time ?? params.startTime : null);
    return {
      ...l,
      capturedCandleTime: candleTime,
    };
  }, [basePrice, params.rangeGap, params.startTime, d.startBar?.candle_time, d.startBar?.start_time]);

  useEffect(() => {
    if (basePrice != null) baseCapturedRef.current = true;
  }, [basePrice]);

  const adaptiveHigh =
    d.engineAdaptiveHigh != null && d.engineAdaptiveHigh > 0
      ? roundPx(d.engineAdaptiveHigh)
      : null;
  const adaptiveLow =
    d.engineAdaptiveLow != null && d.engineAdaptiveLow > 0
      ? roundPx(d.engineAdaptiveLow)
      : null;

  const activeSide = activeSideFromTrades(d.activeTrades);
  const primaryActive = d.activeTrades[0] ?? null;
  const activeLots = primaryActive?.lots ?? 0;

  const activeTpLevels = useMemo(() => {
    if (!primaryActive || levels.upperTrigger == null || levels.lowerTrigger == null) {
      return { tp1: null as number | null, tp2Trail: params.tp2Trail };
    }
    const isCall = /call|ce/i.test(primaryActive.side);
    const entry = isCall ? levels.upperTrigger : levels.lowerTrigger;
    const tp1 = isCall
      ? roundPx(entry + params.firstEntryTp1)
      : roundPx(entry - params.firstEntryTp1);
    return { tp1, tp2Trail: params.tp2Trail };
  }, [primaryActive, levels, params]);

  const tp1Reached = useMemo(() => {
    if (liveIndex == null || activeTpLevels.tp1 == null || activeSide === "NONE") return false;
    if (activeSide === "CALL" || activeSide === "MIXED") return liveIndex >= activeTpLevels.tp1;
    return liveIndex <= activeTpLevels.tp1;
  }, [liveIndex, activeTpLevels.tp1, activeSide]);

  const positionProgress = inferPositionProgress({
    activeLots,
    activeSide,
    sawCoreTp1Today: sawCoreTp1Today(d.tradingLogs),
    isFlat: activeSide === "NONE",
  });

  const phase: StrategyWorkflowPhase = deriveWorkflowPhase({
    startTime: params.startTime,
    endTime: params.endTime,
    basePrice,
    liveIndex,
    upperTrigger: levels.upperTrigger,
    lowerTrigger: levels.lowerTrigger,
    activeSide,
    positionProgress,
    tp1Reached,
    waitReentry: waitReentryFromLogs(d.tradingLogs) && activeSide === "NONE",
  });

  const calculatedRows: CalculatedTradeRow[] = useMemo(
    () => buildCalculatedTradeRows(levels, params, adaptiveHigh, adaptiveLow, liveIndex, activeSide),
    [levels, params, adaptiveHigh, adaptiveLow, liveIndex, activeSide],
  );

  return {
    d,
    liveIndex,
    basePrice,
    params,
    levels,
    phase,
    adaptiveHigh,
    adaptiveLow,
    calculatedRows,
    activeSide,
    primaryActive,
    activeTpLevels,
    positionProgress,
  };
}
