import { fmtDate, fmtPx, round, type Side, type Trade } from "@/lib/backtest-engine";

export function normalizeEntryLots(
  entryLots: number[],
  maxEntries: number,
  initialLots = 2,
  addLots = 1,
): number[] {
  const n = Math.max(1, Math.round(maxEntries));
  const out = entryLots.slice(0, n).map((x) => Math.max(1, Math.round(x)));
  while (out.length < n) {
    out.push(out.length === 0 ? initialLots : out[out.length - 1] ?? addLots);
  }
  return out;
}

export function defaultEntryLots(maxEntries: number, initialLots = 2, addLots = 1): number[] {
  return Array.from({ length: Math.max(1, maxEntries) }, (_, i) => (i === 0 ? initialLots : addLots));
}

export type DaySummaryRow = {
  date: string;
  base: number;
  callTrigger: number;
  putTrigger: number;
  trades: number;
  points: number;
};

export type PlannedLevel = {
  type: string;
  side: string;
  level: number;
  lots: number;
  tp1: number | null;
  tp2Trail: number | null;
  stopLoss: number | null;
  note: string;
};

export type TimelineEvent = {
  time: string;
  event: string;
  label: string;
  side: string;
  price: number | null;
  detail: string;
};

export type ChartCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adaptiveHigh?: number | null;
  adaptiveLow?: number | null;
};

export type DayDetail = {
  date: string;
  base: number;
  callTrigger: number;
  putTrigger: number;
  points: number;
  candles: ChartCandle[];
  plannedLevels: PlannedLevel[];
  timeline: TimelineEvent[];
};

export type TradeRecordRow = {
  uid: string;
  rowNum: number;
  date: string;
  time: string;
  cycleId: string;
  action: string;
  entryType: string;
  side: string;
  basePrice: number | null;
  triggerPrice: number | null;
  indexPrice: number;
  strikeOffset: number | null;
  selectedStrike: string;
  strikeType: string;
  lotsAdded: number | null;
  totalLots: number | null;
  averageEntryPrice: number | null;
  tp1: number | null;
  tp2Trail: number | null;
  adaptiveHigh: number | null;
  adaptiveLow: number | null;
  stopLoss: number | null;
  exitPrice: number | null;
  exitReason: string;
  pnl: number;
  runningPnl: number;
};

export type CycleEntryLeg = {
  label: string;
  time: string;
  indexPrice: number;
  strike: string;
  strikeType: string;
  lots: number;
};

export type CycleTp1Exit = {
  label: string;
  time: string;
  price: number;
  lots: number;
  pnl: number;
};

export type CycleTradeRecord = {
  uid: string;
  order: number;
  date: string;
  cycleId: string;
  side: string;
  cycleKind: "INITIAL" | "REENTRY";
  basePrice: number | null;
  triggerPrice: number | null;
  initialEntry: CycleEntryLeg | null;
  averaging: CycleEntryLeg[];
  firstEntryTp1: CycleTp1Exit | null;
  avgTp1Exits: CycleTp1Exit[];
  tp1Price: number | null;
  tp1ExitLots: number;
  tp1Time: string | null;
  tp2AdaptiveHigh: number | null;
  tp2AdaptiveLow: number | null;
  tp2ExitPrice: number | null;
  tp2Time: string | null;
  tp2Pnl: number | null;
  stopLoss: number | null;
  reentryPrice: number | null;
  reentryStrike: string | null;
  exitReason: string;
  totalLotsUsed: number;
  cyclePnl: number;
  runningPnl: number;
};

/** Flat row for Trade Record table — one row per entry / exit event inside a cycle. */
export type CycleTableRow = {
  uid: string;
  rowNum: number;
  date: string;
  time: string;
  cycleId: string;
  side: string;
  cycleKind: string;
  action: string;
  basePrice: number | null;
  triggerPrice: number | null;
  indexPrice: number | null;
  strike: string;
  strikeType: string;
  lots: number | null;
  totalLots: number | null;
  tp1: number | null;
  adaptiveHigh: number | null;
  adaptiveLow: number | null;
  stopLoss: number | null;
  exitPrice: number | null;
  exitReason: string;
  legPnl: number | null;
  cyclePnl: number | null;
  runningPnl: number | null;
  cycleSummary: boolean;
};

export type NetBreakdown = {
  total: number;
  byDay: { date: string; points: number }[];
  bySide: Record<Side, number>;
  byReason: Record<string, number>;
  byEntryType: Record<string, number>;
};

export function buildPlannedLevelsFromParams(
  base: number,
  p: {
    entryTrigger: number;
    stopDistance: number;
    initialLots: number;
    addLots: number;
    entryLots?: number[];
    averagingGap: number;
    maxEntries: number;
    tp1Points: number;
    firstEntryTp1Points: number;
    tp2Trail: number;
    reEntryGap: number;
    reEntryEnabled: boolean;
  },
): PlannedLevel[] {
  const lots = normalizeEntryLots(p.entryLots ?? [], p.maxEntries, p.initialLots, p.addLots);
  const ce = round(base + p.entryTrigger);
  const pe = round(base - p.entryTrigger);
  const callSl = round(ce - p.stopDistance);
  const putSl = round(pe + p.stopDistance);
  const rows: PlannedLevel[] = [
    { type: "BASE", side: "—", level: round(base), lots: 0, tp1: null, tp2Trail: null, stopLoss: null, note: "09:15 reference close" },
    { type: "CALL_TRIGGER", side: "CALL", level: ce, lots: lots[0], tp1: round(ce + p.firstEntryTp1Points), tp2Trail: p.tp2Trail, stopLoss: callSl, note: `First entry · core TP1 +${p.firstEntryTp1Points}pt · AVG TP1 +${p.tp1Points}pt` },
    { type: "PUT_TRIGGER", side: "PUT", level: pe, lots: lots[0], tp1: round(pe - p.firstEntryTp1Points), tp2Trail: p.tp2Trail, stopLoss: putSl, note: `First entry · core TP1 −${p.firstEntryTp1Points}pt · AVG TP1 −${p.tp1Points}pt` },
  ];
  for (let i = 1; i < p.maxEntries; i++) {
    const avgCall = round(ce - p.averagingGap * i);
    const avgPut = round(pe + p.averagingGap * i);
    if (avgCall > callSl) {
      rows.push({ type: `CALL_AVG_${i}`, side: "CALL", level: avgCall, lots: lots[i] ?? p.addLots, tp1: round(ce + p.tp1Points), tp2Trail: null, stopLoss: callSl, note: `Averaging entry #${i + 1} (TP1 only @ +${p.tp1Points}pt)` });
    }
    if (avgPut < putSl) {
      rows.push({ type: `PUT_AVG_${i}`, side: "PUT", level: avgPut, lots: lots[i] ?? p.addLots, tp1: round(pe - p.tp1Points), tp2Trail: null, stopLoss: putSl, note: `Averaging entry #${i + 1} (TP1 only @ −${p.tp1Points}pt)` });
    }
  }
  if (p.reEntryEnabled) {
    rows.push({ type: "REENTRY_RULE", side: "BOTH", level: p.reEntryGap, lots: lots[0], tp1: null, tp2Trail: null, stopLoss: null, note: `Re-enter on ADP high/low ± ${p.reEntryGap}pt pullback after TP2 (above cycle SL)` });
  }
  return rows;
}

export function buildTimelineFromLog(
  log: Record<string, unknown>[],
  base: number,
  callTrig: number,
  putTrig: number,
): TimelineEvent[] {
  const out: TimelineEvent[] = [
    {
      time: "09:15",
      event: "BASE_CAPTURED",
      label: "Base captured",
      side: "—",
      price: base,
      detail: `Day base = ${base} · Call trigger ${callTrig} · Put trigger ${putTrig}`,
    },
  ];
  for (const row of log) {
    const action = String(row.action ?? "").toUpperCase();
    const side = String(row.side ?? "");
    const entryType = String(row.entry_type ?? "");
    const price = row.index_price != null ? Number(row.index_price) : null;
    const t = String(row.time ?? "");
    if (action === "BUY" || action === "AVERAGE") {
      const kind = entryType === "INITIAL" ? "INITIAL_ENTRY" : entryType === "REENTRY" ? "REENTRY" : "AVERAGE_ENTRY";
      const actionLbl = String(row.action_label ?? action);
      const strikeTxt = String(row.selected_strike_label ?? row.strike ?? "");
      const detail =
        entryType === "AVERAGE"
          ? [
              String(row.strike_detail ?? `Current Index: ${price}\nNearest Strike: ${strikeTxt}`),
              `Lots Added: ${row.lots_added ?? row.lots}`,
              `Total Lots: ${row.total_lots}`,
            ].join("\n")
          : [
              String(row.strike_detail ?? ""),
              `Lots: ${row.lots}`,
              row.tp1 != null ? `TP1: ${row.tp1}` : "",
              row.stop_loss != null ? `SL: ${row.stop_loss}` : "",
            ]
              .filter(Boolean)
              .join("\n");
      out.push({ time: t, event: kind, label: `${actionLbl} · ${side}`, side, price, detail });
    } else if (action === "TP1_PARTIAL") {
      out.push({
        time: t,
        event: "TP1_PARTIAL",
        label: `${row.action_label ?? "TP1 EXIT"} · ${side}`,
        side,
        price: row.exit_price != null ? Number(row.exit_price) : price,
        detail: [
          `Exit Lots: ${row.exit_lots ?? row.lots}`,
          `Remaining Lots: ${row.remaining_lots ?? row.total_lots}`,
          `P&L: ${row.trade_pnl}`,
        ].join("\n"),
      });
    } else if (action === "EXIT") {
      const reason = String(row.exit_reason ?? "");
      const detail =
        reason === "TP2_TRAIL"
          ? [
              row.adaptive_high != null ? `Adaptive High: ${row.adaptive_high}` : null,
              row.adaptive_low != null ? `Adaptive Low: ${row.adaptive_low}` : null,
              `Trail Distance: ${row.tp2_trail}`,
              `Exit Price: ${row.exit_price}`,
              `Remaining Lots: ${row.remaining_lots ?? 0}`,
              `P&L: ${row.trade_pnl}`,
            ]
              .filter(Boolean)
              .join("\n")
          : [
              `Exit Price: ${row.exit_price}`,
              `Exit Reason: ${reason || "closed"}`,
              `P&L: ${row.trade_pnl}`,
            ].join("\n");
      out.push({
        time: t,
        event: reason || "EXIT",
        label: `${row.action_label ?? "EXIT"} · ${side}`,
        side,
        price: row.exit_price != null ? Number(row.exit_price) : price,
        detail,
      });
    }
  }
  return out;
}

export function fallbackDayDetails(
  summaries: DaySummaryRow[],
  log: Record<string, unknown>[],
  params: Parameters<typeof buildPlannedLevelsFromParams>[1],
): DayDetail[] {
  return summaries.map((s) => {
    const dayLog = log.filter((r) => String(r.date) === s.date);
    return {
      date: s.date,
      base: s.base,
      callTrigger: s.callTrigger,
      putTrigger: s.putTrigger,
      points: s.points,
      candles: [],
      plannedLevels: buildPlannedLevelsFromParams(s.base, params),
      timeline: buildTimelineFromLog(dayLog, s.base, s.callTrigger, s.putTrigger),
    };
  });
}

export function mapDaySummary(
  rows: Array<{
    date: string;
    base?: number | null;
    call_trigger?: number | null;
    put_trigger?: number | null;
    trades?: number;
    points?: number;
  }>,
  entryTrigger: number,
): DaySummaryRow[] {
  return rows.map((row) => {
    const base = row.base != null ? round(Number(row.base)) : 0;
    return {
      date: String(row.date),
      base,
      callTrigger: row.call_trigger != null ? round(Number(row.call_trigger)) : round(base + entryTrigger),
      putTrigger: row.put_trigger != null ? round(Number(row.put_trigger)) : round(base - entryTrigger),
      trades: Number(row.trades ?? 0),
      points: round(Number(row.points ?? 0)),
    };
  });
}

export function mapDayDetails(
  rows: Array<Record<string, unknown>>,
  entryTrigger: number,
): DayDetail[] {
  return rows.map((row) => {
    const base = row.base != null ? round(Number(row.base)) : 0;
    const candles = (Array.isArray(row.candles) ? row.candles : []).map((c) => {
      const x = c as Record<string, unknown>;
      return {
        time: String(x.time ?? ""),
        open: Number(x.open ?? 0),
        high: Number(x.high ?? 0),
        low: Number(x.low ?? 0),
        close: Number(x.close ?? 0),
        adaptiveHigh: x.adaptive_high != null ? Number(x.adaptive_high) : null,
        adaptiveLow: x.adaptive_low != null ? Number(x.adaptive_low) : null,
      };
    });
    const planned = (Array.isArray(row.planned_levels) ? row.planned_levels : []).map((p) => {
      const x = p as Record<string, unknown>;
      return {
        type: String(x.type ?? ""),
        side: String(x.side ?? ""),
        level: Number(x.level ?? 0),
        lots: Number(x.lots ?? 0),
        tp1: x.tp1 != null ? Number(x.tp1) : null,
        tp2Trail: x.tp2_trail != null ? Number(x.tp2_trail) : null,
        stopLoss: x.stop_loss != null ? Number(x.stop_loss) : null,
        note: String(x.note ?? ""),
      };
    });
    const timeline = (Array.isArray(row.timeline) ? row.timeline : []).map((t) => {
      const x = t as Record<string, unknown>;
      return {
        time: String(x.time ?? ""),
        event: String(x.event ?? ""),
        label: String(x.label ?? ""),
        side: String(x.side ?? ""),
        price: x.price != null ? Number(x.price) : null,
        detail: String(x.detail ?? ""),
      };
    });
    return {
      date: String(row.date ?? ""),
      base,
      callTrigger: row.call_trigger != null ? round(Number(row.call_trigger)) : round(base + entryTrigger),
      putTrigger: row.put_trigger != null ? round(Number(row.put_trigger)) : round(base - entryTrigger),
      points: round(Number(row.points ?? 0)),
      candles,
      plannedLevels: planned,
      timeline,
    };
  });
}

export function buildTradeRecords(trades: Trade[], log: Record<string, unknown>[]): TradeRecordRow[] {
  if (log.length > 0) {
    return buildTradeRecordsFromLog(log);
  }
  return trades.map((t, i) => ({
    uid: `${t.tradeDate}-${t.id}-${i}`,
    rowNum: i + 1,
    date: t.tradeDate,
    time: t.exitTime,
    cycleId: String(t.id),
    action: "EXIT",
    entryType: t.entryType,
    side: t.side,
    basePrice: null,
    triggerPrice: null,
    indexPrice: t.entry,
    strikeOffset: null,
    selectedStrike: "",
    strikeType: "",
    lotsAdded: t.exitLots,
    totalLots: null,
    averageEntryPrice: null,
    tp1: null,
    tp2Trail: null,
    adaptiveHigh: null,
    adaptiveLow: null,
    stopLoss: null,
    exitPrice: t.exit,
    exitReason: t.note || t.reason,
    pnl: t.points,
    runningPnl: 0,
  }));
}

function mapCycleTp1Exit(raw: Record<string, unknown> | null | undefined): CycleTp1Exit | null {
  if (!raw) return null;
  const price = raw.price != null ? Number(raw.price) : raw.exit_price != null ? Number(raw.exit_price) : null;
  if (price == null) return null;
  return {
    label: String(raw.label ?? "TP1"),
    time: String(raw.time ?? ""),
    price,
    lots: Number(raw.lots ?? raw.exit_lots ?? 0),
    pnl: Number(raw.pnl ?? raw.trade_pnl ?? 0),
  };
}

function mapCycleLeg(raw: Record<string, unknown> | null | undefined): CycleEntryLeg | null {
  if (!raw) return null;
  return {
    label: String(raw.label ?? ""),
    time: String(raw.time ?? ""),
    indexPrice: Number(raw.index_price ?? raw.indexPrice ?? 0),
    strike: String(raw.strike ?? ""),
    strikeType: String(raw.strike_type ?? raw.strikeType ?? ""),
    lots: Number(raw.lots ?? 0),
  };
}

export function mapCycleTradeRecord(raw: Record<string, unknown>, index: number): CycleTradeRecord {
  const averaging = (Array.isArray(raw.averaging) ? raw.averaging : []).map((a) =>
    mapCycleLeg(a as Record<string, unknown>),
  ).filter((x): x is CycleEntryLeg => x != null);

  return {
    uid: `${raw.date}|${raw.cycle_id}|${index}`,
    order: Number(raw.order ?? index + 1),
    date: String(raw.date ?? ""),
    cycleId: String(raw.cycle_id ?? raw.cycleId ?? ""),
    side: String(raw.side ?? ""),
    cycleKind: String(raw.cycle_kind ?? raw.cycleKind ?? "INITIAL") === "REENTRY" ? "REENTRY" : "INITIAL",
    basePrice: raw.base_price != null ? Number(raw.base_price) : raw.basePrice != null ? Number(raw.basePrice) : null,
    triggerPrice: raw.trigger_price != null ? Number(raw.trigger_price) : raw.triggerPrice != null ? Number(raw.triggerPrice) : null,
    initialEntry: mapCycleLeg(
      (raw.initial_entry ?? raw.initialEntry) as Record<string, unknown> | undefined,
    ),
    averaging,
    firstEntryTp1: mapCycleTp1Exit(
      (raw.first_entry_tp1 ?? raw.firstEntryTp1) as Record<string, unknown> | undefined,
    ),
    avgTp1Exits: (Array.isArray(raw.avg_tp1_exits ?? raw.avgTp1Exits)
      ? ((raw.avg_tp1_exits ?? raw.avgTp1Exits) as unknown[])
      : []
    )
      .map((item) => mapCycleTp1Exit(item as Record<string, unknown>))
      .filter((x): x is CycleTp1Exit => x != null),
    tp1Price: raw.tp1_price != null ? Number(raw.tp1_price) : raw.tp1Price != null ? Number(raw.tp1Price) : null,
    tp1ExitLots: Number(raw.tp1_exit_lots ?? raw.tp1ExitLots ?? 0),
    tp1Time: raw.tp1_time != null ? String(raw.tp1_time) : raw.tp1Time != null ? String(raw.tp1Time) : null,
    tp2AdaptiveHigh:
      raw.tp2_adaptive_high != null ? Number(raw.tp2_adaptive_high) : raw.tp2AdaptiveHigh != null ? Number(raw.tp2AdaptiveHigh) : null,
    tp2AdaptiveLow:
      raw.tp2_adaptive_low != null ? Number(raw.tp2_adaptive_low) : raw.tp2AdaptiveLow != null ? Number(raw.tp2AdaptiveLow) : null,
    tp2ExitPrice: raw.tp2_exit_price != null ? Number(raw.tp2_exit_price) : raw.tp2ExitPrice != null ? Number(raw.tp2ExitPrice) : null,
    tp2Time: raw.tp2_time != null ? String(raw.tp2_time) : raw.tp2Time != null ? String(raw.tp2Time) : null,
    tp2Pnl: raw.tp2_pnl != null ? Number(raw.tp2_pnl) : raw.tp2Pnl != null ? Number(raw.tp2Pnl) : null,
    stopLoss: raw.stop_loss != null ? Number(raw.stop_loss) : raw.stopLoss != null ? Number(raw.stopLoss) : null,
    reentryPrice: raw.reentry_price != null ? Number(raw.reentry_price) : raw.reentryPrice != null ? Number(raw.reentryPrice) : null,
    reentryStrike: raw.reentry_strike != null ? String(raw.reentry_strike) : raw.reentryStrike != null ? String(raw.reentryStrike) : null,
    exitReason: String(raw.exit_reason ?? raw.exitReason ?? ""),
    totalLotsUsed: Number(raw.total_lots_used ?? raw.totalLotsUsed ?? 0),
    cyclePnl: Number(raw.cycle_pnl ?? raw.cyclePnl ?? 0),
    runningPnl: Number(raw.running_pnl ?? raw.runningPnl ?? 0),
  };
}

export function buildCycleTradeRecordsFromLog(log: Record<string, unknown>[]): CycleTradeRecord[] {
  const groups = new Map<string, Record<string, unknown>[]>();
  const orderKeys: string[] = [];
  for (const row of log) {
    const key = `${row.date}|${row.cycle_id}`;
    if (!groups.has(key)) {
      groups.set(key, []);
      orderKeys.push(key);
    }
    groups.get(key)!.push(row);
  }

  const records: CycleTradeRecord[] = [];
  for (let i = 0; i < orderKeys.length; i++) {
    const rows = groups.get(orderKeys[i])!;
    if (!rows.length) continue;

    const first = rows[0];
    const side = String(first.side ?? "");
    const entryType = String(first.entry_type ?? "INITIAL");
    const cycleKind: CycleTradeRecord["cycleKind"] = entryType === "REENTRY" ? "REENTRY" : "INITIAL";

    let entryLotsSum = 0;
    let cyclePnl = 0;
    let runningPnl = 0;
    let tp1ExitLots = 0;
    let tp1Price: number | null = null;
    let tp1Time: string | null = null;
    let firstEntryTp1: CycleTp1Exit | null = null;
    const avgTp1Exits: CycleTp1Exit[] = [];
    let tp2ExitPrice: number | null = null;
    let tp2Time: string | null = null;
    let tp2Pnl: number | null = null;
    let tp2AdaptiveHigh: number | null = null;
    let tp2AdaptiveLow: number | null = null;
    let exitReason = "";
    let basePrice: number | null = null;
    let triggerPrice: number | null = null;
    let stopLoss: number | null = null;
    let initialEntry: CycleEntryLeg | null = null;
    let reentryPrice: number | null = null;
    let reentryStrike: string | null = null;
    const averaging: CycleEntryLeg[] = [];

    for (const row of rows) {
      const action = String(row.action ?? "").toUpperCase();
      const et = String(row.entry_type ?? "");
      const strikeLbl = String(row.selected_strike_label ?? row.strike ?? "");

      if (action === "BUY" || action === "AVERAGE") {
        const leg: CycleEntryLeg = {
          label: String(row.action_label ?? action),
          time: String(row.time ?? ""),
          indexPrice: Number(row.current_index_price ?? row.index_price ?? 0),
          strike: strikeLbl,
          strikeType: String(row.strike_type ?? row.strike_selection ?? ""),
          lots: Number(row.lots_added ?? row.lots ?? 0),
        };
        if (et === "INITIAL" || et === "REENTRY") {
          basePrice = row.base_price != null ? Number(row.base_price) : basePrice;
          triggerPrice = row.trigger_price != null ? Number(row.trigger_price) : triggerPrice;
          stopLoss = row.stop_loss != null ? Number(row.stop_loss) : stopLoss;
          initialEntry = leg;
          if (et === "REENTRY") {
            reentryPrice = triggerPrice ?? leg.indexPrice;
            reentryStrike = strikeLbl;
          }
          entryLotsSum += leg.lots;
        } else {
          averaging.push(leg);
          entryLotsSum += leg.lots;
        }
      } else if (action === "TP1_PARTIAL") {
        const reason = String(row.exit_reason ?? "");
        const exitPrice = row.exit_price != null ? Number(row.exit_price) : row.tp1 != null ? Number(row.tp1) : null;
        const exitLots = Number(row.exit_lots ?? row.lots ?? 0);
        const exitPnl = Number(row.trade_pnl ?? 0);
        const exit: CycleTp1Exit = {
          label: reason === "TP1_AVG" ? "Avg TP1" : "First TP1",
          time: String(row.time ?? ""),
          price: exitPrice ?? 0,
          lots: exitLots,
          pnl: exitPnl,
        };
        if (reason === "TP1_AVG") {
          avgTp1Exits.push(exit);
        } else {
          firstEntryTp1 = exit;
        }
        tp1Price = exitPrice ?? tp1Price;
        tp1ExitLots += exitLots;
        tp1Time = String(row.time ?? "");
        if (stopLoss == null && row.stop_loss != null) stopLoss = Number(row.stop_loss);
      } else if (action === "EXIT") {
        exitReason = String(row.exit_reason ?? "");
        tp2ExitPrice = row.exit_price != null ? Number(row.exit_price) : null;
        tp2Time = String(row.time ?? "");
        tp2Pnl = Number(row.trade_pnl ?? 0) || null;
        if (row.adaptive_high != null) tp2AdaptiveHigh = Number(row.adaptive_high);
        if (row.adaptive_low != null) tp2AdaptiveLow = Number(row.adaptive_low);
        if (stopLoss == null && row.stop_loss != null) stopLoss = Number(row.stop_loss);
      }

      const pnl = Number(row.trade_pnl ?? 0);
      if (pnl) cyclePnl += pnl;
      if (row.running_pnl != null) runningPnl = Number(row.running_pnl);
    }

    records.push({
      uid: `${first.date}|${first.cycle_id}|${i}`,
      order: i + 1,
      date: String(first.date ?? ""),
      cycleId: String(first.cycle_id ?? ""),
      side,
      cycleKind,
      basePrice,
      triggerPrice,
      initialEntry,
      averaging,
      firstEntryTp1,
      avgTp1Exits,
      tp1Price,
      tp1ExitLots,
      tp1Time,
      tp2AdaptiveHigh,
      tp2AdaptiveLow,
      tp2ExitPrice,
      tp2Time,
      tp2Pnl,
      stopLoss,
      reentryPrice,
      reentryStrike,
      exitReason,
      totalLotsUsed: entryLotsSum,
      cyclePnl: round(cyclePnl),
      runningPnl,
    });
  }

  return records;
}

export function buildCycleTradeRecords(
  log: Record<string, unknown>[],
  apiRecords?: Record<string, unknown>[],
): CycleTradeRecord[] {
  if (log.length > 0) {
    return buildCycleTradeRecordsFromLog(log);
  }
  if (apiRecords?.length) {
    return apiRecords.map((r, i) => mapCycleTradeRecord(r, i));
  }
  return [];
}

export function flattenCyclesToTableRows(cycles: CycleTradeRecord[]): CycleTableRow[] {
  const rows: CycleTableRow[] = [];
  let rowNum = 0;
  let runningLots = 0;

  for (const c of cycles) {
    const base = {
      date: c.date,
      cycleId: c.cycleId,
      side: c.side,
      cycleKind: c.cycleKind,
      basePrice: c.basePrice,
      triggerPrice: c.triggerPrice,
      stopLoss: c.stopLoss,
      tp1: c.tp1Price,
    };

    const push = (partial: Omit<CycleTableRow, "uid" | "rowNum">) => {
      rowNum += 1;
      rows.push({
        uid: `${c.uid}|${rowNum}|${partial.action}`,
        rowNum,
        ...partial,
      });
    };

    runningLots = 0;

    if (c.initialEntry) {
      runningLots += c.initialEntry.lots;
      push({
        ...base,
        time: c.initialEntry.time,
        action: c.cycleKind === "REENTRY" ? "BUY REENTRY" : "BUY INITIAL",
        indexPrice: c.initialEntry.indexPrice,
        strike: c.initialEntry.strike,
        strikeType: c.initialEntry.strikeType || "Offset",
        lots: c.initialEntry.lots,
        totalLots: runningLots,
        adaptiveHigh: null,
        adaptiveLow: null,
        exitPrice: null,
        exitReason: "",
        legPnl: null,
        cyclePnl: null,
        runningPnl: null,
        cycleSummary: false,
      });
    }

    for (const a of c.averaging) {
      runningLots += a.lots;
      push({
        ...base,
        time: a.time,
        action: a.label || "BUY AVG",
        indexPrice: a.indexPrice,
        strike: a.strike,
        strikeType: a.strikeType || "Nearest",
        lots: a.lots,
        totalLots: runningLots,
        adaptiveHigh: null,
        adaptiveLow: null,
        exitPrice: null,
        exitReason: "",
        legPnl: null,
        cyclePnl: null,
        runningPnl: null,
        cycleSummary: false,
      });
    }

    if (c.tp1Price != null && c.tp1ExitLots > 0) {
      push({
        ...base,
        time: c.tp1Time ?? "",
        action: "TP1 EXIT",
        indexPrice: c.tp1Price,
        strike: c.initialEntry?.strike ?? c.reentryStrike ?? "",
        strikeType: "Offset",
        lots: c.tp1ExitLots,
        totalLots: Math.max(0, runningLots - c.tp1ExitLots),
        adaptiveHigh: null,
        adaptiveLow: null,
        exitPrice: c.tp1Price,
        exitReason: "TP1",
        legPnl: null,
        cyclePnl: null,
        runningPnl: null,
        cycleSummary: false,
      });
    }

    const exitAction =
      c.exitReason === "TP2_TRAIL"
        ? "TP2 EXIT"
        : c.exitReason === "INDEX_SL"
          ? "SL EXIT"
          : c.exitReason === "SESSION_END"
            ? "SESSION EXIT"
            : c.exitReason
              ? "EXIT"
              : "CYCLE END";

    push({
      ...base,
      time: c.tp2Time ?? "",
      action: exitAction,
      indexPrice: c.tp2ExitPrice,
      strike: c.initialEntry?.strike ?? c.reentryStrike ?? "",
      strikeType: "Offset",
      lots: c.totalLotsUsed > 0 ? Math.max(1, c.totalLotsUsed - c.tp1ExitLots) : null,
      totalLots: 0,
      adaptiveHigh: c.tp2AdaptiveHigh,
      adaptiveLow: c.tp2AdaptiveLow,
      exitPrice: c.tp2ExitPrice,
      exitReason: c.exitReason || exitAction,
      legPnl: null,
      cyclePnl: c.cyclePnl,
      runningPnl: c.runningPnl,
      cycleSummary: true,
    });
  }

  return rows;
}

/** Flat rows from backtest trade log — per-event SL and actions. */
export function flattenLogToTableRows(log: Record<string, unknown>[]): CycleTableRow[] {
  const rows: CycleTableRow[] = [];
  const cyclePnlAcc = new Map<string, number>();

  for (let i = 0; i < log.length; i++) {
    const row = log[i];
    const action = String(row.action ?? "").toUpperCase();
    const cycleKey = `${row.date}|${row.cycle_id}`;
    const actionLabel = String(row.action_label ?? row.action ?? "");
    const entryType = String(row.entry_type ?? "");
    const isEntry = action === "BUY" || action === "AVERAGE";
    const isTp1 = action === "TP1_PARTIAL";
    const isExit = action === "EXIT";

    const pnl = Number(row.trade_pnl ?? 0);
    if ((isTp1 || isExit) && pnl) {
      cyclePnlAcc.set(cycleKey, (cyclePnlAcc.get(cycleKey) ?? 0) + pnl);
    }

    let cycleKind = "";
    if (isEntry) {
      cycleKind = entryType === "REENTRY" ? "REENTRY" : entryType === "INITIAL" ? "INITIAL" : "AVERAGE";
    } else if (entryType) {
      cycleKind = entryType;
    }

    rows.push({
      uid: `${cycleKey}|${i}|${actionLabel}`,
      rowNum: i + 1,
      date: String(row.date ?? ""),
      time: String(row.time ?? ""),
      cycleId: String(row.cycle_id ?? ""),
      side: String(row.side ?? ""),
      cycleKind,
      action: actionLabel,
      basePrice: row.base_price != null ? Number(row.base_price) : null,
      triggerPrice: row.trigger_price != null ? Number(row.trigger_price) : null,
      indexPrice: null,
      strike: String(row.selected_strike_label ?? row.strike ?? ""),
      strikeType: String(row.strike_type ?? row.strike_selection ?? "Offset"),
      lots: isEntry
        ? Number(row.lots ?? 0)
        : isTp1 || isExit
          ? Number(row.exit_lots ?? row.lots ?? 0)
          : null,
      totalLots:
        row.total_lots != null
          ? Number(row.total_lots)
          : row.remaining_lots != null
            ? Number(row.remaining_lots)
            : null,
      tp1: row.tp1 != null ? Number(row.tp1) : null,
      adaptiveHigh: row.adaptive_high != null ? Number(row.adaptive_high) : null,
      adaptiveLow: row.adaptive_low != null ? Number(row.adaptive_low) : null,
      stopLoss: row.stop_loss != null ? Number(row.stop_loss) : null,
      exitPrice: isTp1 || isExit ? (row.exit_price != null ? Number(row.exit_price) : null) : null,
      exitReason: isTp1 || isExit ? String(row.exit_reason ?? row.reason_label ?? "") : "",
      legPnl: isTp1 || isExit ? (pnl || null) : null,
      cyclePnl: isExit ? (cyclePnlAcc.get(cycleKey) ?? null) : null,
      runningPnl: row.running_pnl != null ? Number(row.running_pnl) : null,
      cycleSummary: isExit,
    });
  }

  return rows;
}

export function cycleTableRowsToExportRows(rows: CycleTableRow[]): (string | number)[][] {
  return rows.map((r) => [
    r.rowNum,
    fmtDate(r.date),
    r.time,
    r.cycleId,
    r.action,
    r.side,
    r.cycleKind,
    r.basePrice ?? "",
    r.triggerPrice ?? "",
    r.strike,
    r.strikeType,
    r.lots ?? "",
    r.totalLots ?? "",
    r.tp1 ?? "",
    r.adaptiveHigh ?? r.adaptiveLow ?? "",
    r.stopLoss ?? "",
    r.exitPrice ?? "",
    r.exitReason,
    r.cyclePnl ?? "",
    r.runningPnl ?? "",
  ]);
}

export function cycleRecordsToExportRows(records: CycleTradeRecord[]): (string | number)[][] {
  return records.map((record, index) => cycleRecordToFlatRow(record, index + 1));
}

export const TRADE_RECORD_FLAT_HEADERS = [
  "#",
  "Date",
  "Cycle",
  "Trade Type",
  "Side",
  "Base Price",
  "Trigger Price",
  "Entry Time",
  "Sensex Entry Price",
  "Option Entry Strike",
  "Entry Lots",
  "AVG1 Time",
  "AVG1 Price",
  "AVG1 Strike",
  "AVG2 Time",
  "AVG2 Price",
  "AVG2 Strike",
  "AVG3 Time",
  "AVG3 Price",
  "AVG3 Strike",
  "TP1 Time",
  "TP1 Price",
  "TP1 Lots",
  "TP2 Time",
  "TP2 Price",
  "TP2 Lots",
  "Stop Loss",
  "Exit Time",
  "Exit Price",
  "Exit Reason",
  "Total Lots",
  "Cycle P&L",
  "Running P&L",
] as const;

const TRADE_RECORD_EMPTY = "--";

function tradeRecordCell(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return TRADE_RECORD_EMPTY;
  if (typeof v === "number" && !Number.isFinite(v)) return TRADE_RECORD_EMPTY;
  return String(v);
}

function tradeRecordPx(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return TRADE_RECORD_EMPTY;
  return fmtPx(v);
}

function tradeRecordAvgCells(leg: CycleEntryLeg | null): [string, string, string] {
  if (!leg) return [TRADE_RECORD_EMPTY, TRADE_RECORD_EMPTY, TRADE_RECORD_EMPTY];
  return [tradeRecordCell(leg.time), tradeRecordPx(leg.indexPrice), tradeRecordCell(leg.strike)];
}

export function cycleRecordToFlatRow(record: CycleTradeRecord, rowNum: number): (string | number)[] {
  const entry = record.initialEntry;
  const avg1 = tradeRecordAvgCells(record.averaging[0] ?? null);
  const avg2 = tradeRecordAvgCells(record.averaging[1] ?? null);
  const avg3 = tradeRecordAvgCells(record.averaging[2] ?? null);

  const tp1 = record.firstEntryTp1 ?? record.avgTp1Exits[0] ?? null;
  const tp1Time = tp1?.time ?? record.tp1Time;
  const tp1Price = tp1?.price ?? record.tp1Price;
  const tp1Lots = tp1?.lots ?? (record.tp1ExitLots > 0 ? record.tp1ExitLots : null);

  const tp2Lots =
    record.tp2ExitPrice != null && record.totalLotsUsed > 0
      ? Math.max(0, record.totalLotsUsed - record.tp1ExitLots)
      : null;

  return [
    rowNum,
    fmtDate(record.date),
    record.cycleId,
    record.cycleKind === "INITIAL" ? "Initial Trade" : "Re-entry Trade",
    record.side,
    tradeRecordPx(record.basePrice),
    tradeRecordPx(record.triggerPrice),
    tradeRecordCell(entry?.time),
    tradeRecordPx(entry?.indexPrice),
    tradeRecordCell(entry?.strike),
    entry?.lots != null && entry.lots > 0 ? entry.lots : TRADE_RECORD_EMPTY,
    avg1[0],
    avg1[1],
    avg1[2],
    avg2[0],
    avg2[1],
    avg2[2],
    avg3[0],
    avg3[1],
    avg3[2],
    tradeRecordCell(tp1Time),
    tradeRecordPx(tp1Price),
    tp1Lots != null && tp1Lots > 0 ? tp1Lots : TRADE_RECORD_EMPTY,
    tradeRecordCell(record.tp2Time),
    tradeRecordPx(record.tp2ExitPrice),
    tp2Lots != null && tp2Lots > 0 ? tp2Lots : TRADE_RECORD_EMPTY,
    tradeRecordPx(record.stopLoss),
    tradeRecordCell(record.tp2Time),
    tradeRecordPx(record.tp2ExitPrice),
    tradeRecordCell(record.exitReason),
    record.totalLotsUsed > 0 ? record.totalLotsUsed : TRADE_RECORD_EMPTY,
    record.cyclePnl,
    record.runningPnl,
  ];
}

export function buildTradeRecordsFromLog(log: Record<string, unknown>[]): TradeRecordRow[] {
  const rows: TradeRecordRow[] = [];

  for (let i = 0; i < log.length; i++) {
    const row = log[i];
    const date = String(row.date ?? "");
    const action = String(row.action_label ?? row.action ?? "");
    const entryType = String(row.entry_type ?? "");
    const actionUpper = String(row.action ?? "").toUpperCase();
    const isExit = actionUpper === "TP1_PARTIAL" || actionUpper === "EXIT";

    rows.push({
      uid: `${date}|${String(row.time)}|${String(row.cycle_id)}|${action}|${i}`,
      rowNum: i + 1,
      date,
      time: String(row.time ?? ""),
      cycleId: String(row.cycle_id ?? ""),
      action,
      entryType,
      side: String(row.side ?? ""),
      basePrice: row.base_price != null ? Number(row.base_price) : null,
      triggerPrice: row.trigger_price != null ? Number(row.trigger_price) : null,
      indexPrice: Number(row.current_index_price ?? row.index_price ?? 0),
      strikeOffset: row.strike_offset != null ? Number(row.strike_offset) : null,
      selectedStrike: String(row.selected_strike_label ?? row.strike ?? ""),
      strikeType: String(row.strike_type ?? row.strike_selection ?? ""),
      lotsAdded: isExit
        ? row.exit_lots != null
          ? Number(row.exit_lots)
          : Number(row.lots ?? 0)
        : row.lots_added != null
          ? Number(row.lots_added)
          : Number(row.lots ?? 0),
      totalLots: row.total_lots != null ? Number(row.total_lots) : row.remaining_lots != null ? Number(row.remaining_lots) : null,
      averageEntryPrice: row.average_entry_price != null ? Number(row.average_entry_price) : null,
      tp1: row.tp1 != null ? Number(row.tp1) : null,
      tp2Trail: row.tp2_trail != null ? Number(row.tp2_trail) : null,
      adaptiveHigh: row.adaptive_high != null ? Number(row.adaptive_high) : null,
      adaptiveLow: row.adaptive_low != null ? Number(row.adaptive_low) : null,
      stopLoss: row.stop_loss != null ? Number(row.stop_loss) : null,
      exitPrice: row.exit_price != null ? Number(row.exit_price) : null,
      exitReason: String(row.exit_reason ?? row.reason_label ?? ""),
      pnl: Number(row.trade_pnl ?? 0),
      runningPnl: Number(row.running_pnl ?? 0),
    });
  }
  return rows;
}

export function buildNetBreakdown(
  daySummaries: DaySummaryRow[],
  trades: Trade[],
): NetBreakdown {
  const bySide: Record<Side, number> = { CALL: 0, PUT: 0 };
  const byReason: Record<string, number> = {};
  const byEntryType: Record<string, number> = {};

  for (const t of trades) {
    bySide[t.side] = (bySide[t.side] ?? 0) + t.points;
    byReason[t.reason] = (byReason[t.reason] ?? 0) + t.points;
    byEntryType[t.entryType] = (byEntryType[t.entryType] ?? 0) + t.points;
  }

  return {
    total: round(daySummaries.reduce((a, d) => a + d.points, 0)),
    byDay: daySummaries.map((d) => ({ date: d.date, points: d.points })),
    bySide,
    byReason,
    byEntryType,
  };
}

export function exportExcelBlob(sections: { title: string; headers: string[]; rows: (string | number)[][] }[]) {
  const BOM = "\uFEFF";
  const parts = sections.map((s) => {
    const head = [s.title, "", ...s.headers.map(csvCell).join(",")];
    const body = s.rows.map((r) => r.map(csvCell).join(","));
    return [...head, ...body].join("\r\n");
  });
  return new Blob([BOM + parts.join("\r\n\r\n")], { type: "application/vnd.ms-excel;charset=utf-8" });
}

function csvCell(v: unknown) {
  return `"${String(v ?? "").replaceAll('"', '""')}"`;
}

export function levelTypeLabel(type: string): string {
  return type
    .replaceAll("_", " ")
    .replace("CALL TRIGGER", "Call Trigger")
    .replace("PUT TRIGGER", "Put Trigger")
    .replace("REENTRY RULE", "Re-entry Rule");
}

export { fmtDate, fmtPx };
