export type BacktestResult = {
  trades: Trade[];
  adaptiveHigh: number | null;
  adaptiveLow: number | null;
  finalCallTrigger?: number | null;
  finalPutTrigger?: number | null;
  events?: BacktestEvent[];
};

export type Side = "CALL" | "PUT";
export type Reason = "TP1" | "TP2" | "SL" | "SESSION_END";
export type EntryType = "INITIAL" | "TP1_REFILL" | "TP2_REMAINING" | "TP2_PULLBACK" | "SL_SWITCH" | "ADAPTIVE_HIGH" | "ADAPTIVE_LOW";
export type Candle = { time: string; open: number; high: number; low: number; close: number };
export type Trade = {
  id: number;
  tradeDate: string;
  side: Side;
  entryTime: string;
  exitTime: string;
  entry: number;
  exit: number;
  entryLots: number;
  exitLots: number;
  points: number;
  reason: Reason;
  entryType: EntryType;
  note: string;
};
export type BacktestEventType = "BASE" | "NEW_HIGH" | "NEW_LOW" | "ENTRY";
export type BacktestEvent = {
  id: number;
  tradeDate: string;
  time: string;
  type: BacktestEventType;
  price: number;
  adaptiveHigh: number;
  adaptiveLow: number;
  callTrigger: number;
  putTrigger: number;
  side?: Side;
  source: string;
};
type Position = {
  side: Side;
  entryTime: string;
  entry: number;
  tp2Held: number;
  tp1Active: number;
  tp2LegEntryTime: string;
  tp2LegEntryType: EntryType;
  tp1LegEntryTime: string;
  tp1LegEntryType: EntryType;
  tp1: number;
  tp2: number;
  sl: number;
  tp1Done: boolean;
  entryType: EntryType;
  refillArmed: boolean;
  tp2Only: boolean;
  tp1RearmRequired: boolean;
  firstTp1Pending: boolean;
};
type PullbackWatch = { side: Side; tp1: number; tp2: number; sl: number } | null;
export type Settings = {
  startTime: string;
  endTime: string;
  base: number;
  rangeGap: number;
  tp1Points: number;
  tp1Lots: number;
  tp2Points: number;
  tp2Lots: number;
  firstEntryEnabled: boolean;
  adaptiveCallRetraceHigh: number;
  adaptivePutRetraceHigh: number;
  adaptivePutRetraceLow: number;
  adaptiveCallRetraceLow: number;
};

export type StrategyParams = Omit<Settings, "base">;

export type DaySummary = {
  date: string;
  base: number;
  upper: number;
  lower: number;
  adaptiveHigh: number | null;
  adaptiveLow: number | null;
  trackAdaptiveHigh: boolean;
  trackAdaptiveLow: boolean;
  callTrigHigh: number | null;
  putTrigHigh: number | null;
  putTrigLow: number | null;
  callTrigLow: number | null;
  trades: number;
  points: number;
};

export type PlannedLevelRow = {
  date: string;
  type: string;
  entry: number;
  lots: number;
  tp1: number;
  tp2: number;
  sl: number;
  status: string;
};

export const MAX_BACKTEST_DAYS = 366;
export const round = (n: number) => Math.round(n * 100) / 100;
export const shortTime = (s: string) => s.replace("T", " ").slice(11, 16) || s.slice(0, 5);
export const fmtDate = (iso: string) => {
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${d}/${m}/${y}`;
};
export const fmtTradeDt = (iso: string, hm: string) => `${fmtDate(iso)} ${hm}`;
export const fmtPx = (n: number | string) =>
  typeof n === "number"
    ? n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : n;
/** Empty cell placeholder (ASCII only — avoids mojibake in CSV/Excel). */
export const dash = (n: number | null | undefined) => (n != null && n > 0 ? fmtPx(n) : "-");

export function addDaysIso(iso: string, days: number) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + days);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

export function dateRange(from: string, to: string) {
  if (!from || !to || from > to) return [];
  const out: string[] = [];
  let cur = from;
  while (cur <= to) {
    out.push(cur);
    cur = addDaysIso(cur, 1);
  }
  return out;
}
export function entryTypeLabel(t: EntryType) {
  if (t === "TP2_REMAINING") return "TP2 REMAINING";
  return t.replaceAll("_", " ");
}

export function buildPlannedLevels(date: string, base: number, p: StrategyParams): PlannedLevelRow[] {
  const upper = round(base + p.rangeGap);
  const lower = round(base - p.rangeGap);
  const callTp1 = round(upper + p.tp1Points);
  const callTp2 = round(upper + p.tp2Points);
  const putTp1 = round(lower - p.tp1Points);
  const putTp2 = round(lower - p.tp2Points);
  return [
    { date, type: "Initial Call Entry", entry: upper, lots: p.tp1Lots + p.tp2Lots, tp1: callTp1, tp2: callTp2, sl: lower, status: "Pending" },
    { date, type: "Initial Put Entry", entry: lower, lots: p.tp1Lots + p.tp2Lots, tp1: putTp1, tp2: putTp2, sl: upper, status: "Pending" },
    { date, type: "Call TP1 Refill", entry: upper, lots: p.tp1Lots, tp1: callTp1, tp2: callTp2, sl: lower, status: `Refill ${fmtPx(callTp1)} -> ${fmtPx(upper)}` },
    { date, type: "Put TP1 Refill", entry: lower, lots: p.tp1Lots, tp1: putTp1, tp2: putTp2, sl: upper, status: `Refill ${fmtPx(putTp1)} -> ${fmtPx(lower)}` },
    { date, type: "Call TP2 Re-entry", entry: callTp1, lots: p.tp2Lots, tp1: callTp1, tp2: callTp2, sl: lower, status: `Re-entry @ ${fmtPx(callTp1)}` },
    { date, type: "Put TP2 Re-entry", entry: putTp1, lots: p.tp2Lots, tp1: putTp1, tp2: putTp2, sl: upper, status: `Re-entry @ ${fmtPx(putTp1)}` },
  ];
}

export function buildDaySummary(date: string, base: number, result: BacktestResult, p: StrategyParams): DaySummary {
  const trackHigh = result.adaptiveHigh != null;
  const trackLow = result.adaptiveLow != null;
  const ah = trackHigh ? result.adaptiveHigh : null;
  const al = trackLow ? result.adaptiveLow : null;
  return {
    date,
    base: round(base),
    upper: round(result.finalCallTrigger ?? base + p.rangeGap),
    lower: round(result.finalPutTrigger ?? base - p.rangeGap),
    adaptiveHigh: ah,
    adaptiveLow: al,
    trackAdaptiveHigh: trackHigh,
    trackAdaptiveLow: trackLow,
    callTrigHigh: trackHigh && ah != null ? round(ah - p.adaptiveCallRetraceHigh) : null,
    putTrigHigh: trackHigh && ah != null ? round(ah - p.adaptivePutRetraceHigh) : null,
    putTrigLow: trackLow && al != null ? round(al + p.adaptivePutRetraceLow) : null,
    callTrigLow: trackLow && al != null ? round(al + p.adaptiveCallRetraceLow) : null,
    trades: result.trades.length,
    points: round(result.trades.reduce((a, t) => a + t.points, 0)),
  };
}

function posLots(pos: Position) {
  return pos.tp2Held + pos.tp1Active;
}

export function runBacktest(candles: Candle[], s: Settings, tradeDate: string): BacktestResult {
  const trades: Trade[] = [];
  const events: BacktestEvent[] = [];
  let adaptiveHigh = round(s.base);
  let adaptiveLow = round(s.base);
  const callTrigger = () => round(adaptiveLow + s.rangeGap);
  const putTrigger = () => round(adaptiveHigh - s.rangeGap);
  const slForSide = (side: Side) => (side === "CALL" ? putTrigger() : callTrigger());
  let active: Position | null = null;
  let id = 1;
  let callCompleted = false;
  let putCompleted = false;
  let initialUsed = false;
  let pullbackWatch: PullbackWatch = null;
  let eventId = 1;
  const addEvent = (c: Candle, type: BacktestEventType, price: number, source: string, side?: Side) => {
    events.push({
      id: eventId++,
      tradeDate,
      time: shortTime(c.time),
      type,
      price: round(price),
      adaptiveHigh: round(adaptiveHigh),
      adaptiveLow: round(adaptiveLow),
      callTrigger: callTrigger(),
      putTrigger: putTrigger(),
      side,
      source,
    });
  };

  const exit = (
    pos: Position,
    c: Candle,
    price: number,
    exitLots: number,
    meta: { entryTime: string; entryType: EntryType; entryLots: number },
    reason: Reason,
    note: string,
  ) => {
    const raw = pos.side === "CALL" ? price - pos.entry : pos.entry - price;
    trades.push({
      id: id++,
      tradeDate,
      side: pos.side,
      entryTime: meta.entryTime,
      exitTime: shortTime(c.time),
      entry: round(pos.entry),
      exit: round(price),
      entryLots: meta.entryLots,
      exitLots,
      points: round(raw * exitLots),
      reason,
      entryType: meta.entryType,
      note,
    });
  };
  const enter = (
    side: Side,
    entry: number,
    time: string,
    entryType: EntryType,
    lots = s.tp1Lots + s.tp2Lots,
    levels?: { tp1: number; tp2: number; sl: number; tp2Only?: boolean },
  ): Position => {
    const tp2Only = Boolean(levels?.tp2Only);
    const legTime = shortTime(time);
    return {
      side,
      entry: round(entry),
      entryTime: legTime,
      tp2Held: tp2Only ? lots : 0,
      tp1Active: tp2Only ? 0 : lots,
      tp2LegEntryTime: legTime,
      tp2LegEntryType: entryType,
      tp1LegEntryTime: legTime,
      tp1LegEntryType: entryType,
      tp1: round(levels?.tp1 ?? (side === "CALL" ? entry + s.tp1Points : entry - s.tp1Points)),
      tp2: round(levels?.tp2 ?? (side === "CALL" ? entry + s.tp2Points : entry - s.tp2Points)),
      sl: round(levels?.sl ?? slForSide(side)),
      tp1Done: false,
      entryType,
      refillArmed: false,
      tp2Only,
      tp1RearmRequired: false,
      firstTp1Pending: !tp2Only,
    };
  };
  const applyRefill = (pos: Position, c: Candle) => {
    pos.tp1Active = s.tp1Lots;
    pos.tp1Done = false;
    pos.refillArmed = false;
    pos.tp1RearmRequired = false;
    pos.tp1LegEntryTime = shortTime(c.time);
    pos.tp1LegEntryType = "TP1_REFILL";
    pos.entryType = "TP1_REFILL";
    pos.entryTime = pos.tp1LegEntryTime;
  };

  if (candles.length) {
    addEvent(candles[0], "BASE", s.base, "Start candle close seeds Adaptive High and Adaptive Low");
  }

  for (let i = 1; i < candles.length; i++) {
    const c = candles[i];
    if (c.high > adaptiveHigh) {
      adaptiveHigh = round(c.high);
      addEvent(c, "NEW_HIGH", c.high, `New high updates PUT trigger only: ${fmtPx(adaptiveHigh)} - ${s.rangeGap}`);
    }
    if (c.low < adaptiveLow) {
      adaptiveLow = round(c.low);
      addEvent(c, "NEW_LOW", c.low, `New low updates CALL trigger only: ${fmtPx(adaptiveLow)} + ${s.rangeGap}`);
    }

    if (!active && pullbackWatch) {
      if (pullbackWatch.side === "CALL" && c.low <= pullbackWatch.tp1) {
        active = enter("CALL", pullbackWatch.tp1, c.time, "TP2_PULLBACK", s.tp2Lots, {
          tp1: pullbackWatch.tp1,
          tp2: pullbackWatch.tp2,
          sl: pullbackWatch.sl,
          tp2Only: true,
        });
        active.tp1Done = true;
        pullbackWatch = null;
      } else if (pullbackWatch.side === "PUT" && c.high >= pullbackWatch.tp1) {
        active = enter("PUT", pullbackWatch.tp1, c.time, "TP2_PULLBACK", s.tp2Lots, {
          tp1: pullbackWatch.tp1,
          tp2: pullbackWatch.tp2,
          sl: pullbackWatch.sl,
          tp2Only: true,
        });
        active.tp1Done = true;
        pullbackWatch = null;
      }
    }

    if (!active) {
      const dynCall = callTrigger();
      const dynPut = putTrigger();
      if (!initialUsed && s.firstEntryEnabled && c.high >= dynCall) {
        addEvent(c, "ENTRY", dynCall, `CALL from Adaptive Low ${fmtPx(adaptiveLow)} + Range ${s.rangeGap}`, "CALL");
        active = enter("CALL", dynCall, c.time, "INITIAL", s.tp1Lots + s.tp2Lots, {
          tp1: dynCall + s.tp1Points,
          tp2: dynCall + s.tp2Points,
          sl: dynPut,
        });
        initialUsed = true;
        pullbackWatch = null;
      } else if (!initialUsed && s.firstEntryEnabled && c.low <= dynPut) {
        addEvent(c, "ENTRY", dynPut, `PUT from Adaptive High ${fmtPx(adaptiveHigh)} - Range ${s.rangeGap}`, "PUT");
        active = enter("PUT", dynPut, c.time, "INITIAL", s.tp1Lots + s.tp2Lots, {
          tp1: dynPut - s.tp1Points,
          tp2: dynPut - s.tp2Points,
          sl: dynCall,
        });
        initialUsed = true;
        pullbackWatch = null;
      } else if (callCompleted && c.low <= adaptiveHigh - s.adaptiveCallRetraceHigh) {
        const entry = round(adaptiveHigh - s.adaptiveCallRetraceHigh);
        addEvent(c, "ENTRY", entry, `CALL retrace from recent high ${fmtPx(adaptiveHigh)} - ${s.adaptiveCallRetraceHigh}`, "CALL");
        active = enter("CALL", entry, c.time, "ADAPTIVE_HIGH");
        pullbackWatch = null;
      } else if (callCompleted && c.low <= adaptiveHigh - s.adaptivePutRetraceHigh) {
        const entry = round(adaptiveHigh - s.adaptivePutRetraceHigh);
        addEvent(c, "ENTRY", entry, `PUT retrace from recent high ${fmtPx(adaptiveHigh)} - ${s.adaptivePutRetraceHigh}`, "PUT");
        active = enter("PUT", entry, c.time, "ADAPTIVE_HIGH");
        pullbackWatch = null;
      } else if (putCompleted && c.high >= adaptiveLow + s.adaptivePutRetraceLow) {
        const entry = round(adaptiveLow + s.adaptivePutRetraceLow);
        addEvent(c, "ENTRY", entry, `PUT retrace from recent low ${fmtPx(adaptiveLow)} + ${s.adaptivePutRetraceLow}`, "PUT");
        active = enter("PUT", entry, c.time, "ADAPTIVE_LOW");
        pullbackWatch = null;
      } else if (putCompleted && c.high >= adaptiveLow + s.adaptiveCallRetraceLow) {
        const entry = round(adaptiveLow + s.adaptiveCallRetraceLow);
        addEvent(c, "ENTRY", entry, `CALL retrace from recent low ${fmtPx(adaptiveLow)} + ${s.adaptiveCallRetraceLow}`, "CALL");
        active = enter("CALL", entry, c.time, "ADAPTIVE_LOW");
        pullbackWatch = null;
      }
    }
    if (!active) continue;

    if (active.side === "CALL") {
      if (active.tp1RearmRequired && c.low < active.tp1) {
        active.tp1RearmRequired = false;
      }
      const currentSl = slForSide("CALL");
      if (c.low <= currentSl) {
        const remaining = posLots(active);
        exit(
          active,
          c,
          currentSl,
          remaining,
          { entryTime: active.tp2LegEntryTime, entryType: active.tp2LegEntryType, entryLots: remaining },
          "SL",
          "Spot hit lower trigger. Full CALL position closed; PUT side activated.",
        );
        const entry = putTrigger();
        addEvent(c, "ENTRY", entry, `SL switch PUT from current Adaptive High ${fmtPx(adaptiveHigh)} - Range ${s.rangeGap}`, "PUT");
        active = enter("PUT", entry, c.time, "SL_SWITCH", s.tp1Lots + s.tp2Lots, {
          tp1: entry - s.tp1Points,
          tp2: entry - s.tp2Points,
          sl: callTrigger(),
        });
        pullbackWatch = null;
        putCompleted = false;
        continue;
      }
      if (!active.tp2Only && !active.tp1Done && !active.tp1RearmRequired && c.high >= active.tp1) {
        const exitLots = Math.min(s.tp1Lots, active.tp1Active || s.tp1Lots);
        const isFirstTp1 = active.firstTp1Pending;
        exit(
          active,
          c,
          active.tp1,
          exitLots,
          isFirstTp1
            ? { entryTime: active.tp1LegEntryTime, entryType: active.tp1LegEntryType, entryLots: s.tp1Lots + s.tp2Lots }
            : { entryTime: active.tp1LegEntryTime, entryType: active.tp1LegEntryType, entryLots: active.tp1Active },
          "TP1",
          isFirstTp1
            ? `TP1 hit. ${exitLots} of ${s.tp1Lots + s.tp2Lots} lots booked at TP1; ${s.tp2Lots} lots held for TP2 from ${active.tp2LegEntryTime} entry.`
            : `TP1 hit. ${exitLots} refill lots (entered ${active.tp1LegEntryTime}) booked at TP1.`,
        );
        if (active.firstTp1Pending) {
          active.tp2Held = s.tp2Lots;
          active.tp1Active = 0;
          active.firstTp1Pending = false;
        } else {
          active.tp1Active = 0;
        }
        active.tp1Done = true;
        active.refillArmed = true;
        active.tp1RearmRequired = true;
      }
      if (active.refillArmed && c.low <= active.entry && active.tp1Active === 0 && active.tp2Held === s.tp2Lots) {
        applyRefill(active, c);
      }
      if (c.high >= active.tp2 && active.tp2Held > 0) {
        const exitLots = active.tp2Held;
        exit(
          active,
          c,
          active.tp2,
          exitLots,
          { entryTime: active.tp2LegEntryTime, entryType: "TP2_REMAINING", entryLots: exitLots },
          "TP2",
          `TP2 hit. ${exitLots} remaining TP2 lots (held since ${active.tp2LegEntryType.replaceAll("_", " ")} at ${active.tp2LegEntryTime}) closed at TP2.`,
        );
        active.tp2Held = 0;
        if (active.tp1Active <= 0) {
          pullbackWatch = { side: "CALL", tp1: active.tp1, tp2: active.tp2, sl: slForSide("CALL") };
          active = null;
          callCompleted = true;
        }
      }
    } else {
      if (active.tp1RearmRequired && c.high > active.tp1) {
        active.tp1RearmRequired = false;
      }
      const currentSl = slForSide("PUT");
      if (c.high >= currentSl) {
        const remaining = posLots(active);
        exit(
          active,
          c,
          currentSl,
          remaining,
          { entryTime: active.tp2LegEntryTime, entryType: active.tp2LegEntryType, entryLots: remaining },
          "SL",
          "Spot hit upper trigger. Full PUT position closed; CALL side activated.",
        );
        const entry = callTrigger();
        addEvent(c, "ENTRY", entry, `SL switch CALL from current Adaptive Low ${fmtPx(adaptiveLow)} + Range ${s.rangeGap}`, "CALL");
        active = enter("CALL", entry, c.time, "SL_SWITCH", s.tp1Lots + s.tp2Lots, {
          tp1: entry + s.tp1Points,
          tp2: entry + s.tp2Points,
          sl: putTrigger(),
        });
        pullbackWatch = null;
        callCompleted = false;
        continue;
      }
      if (!active.tp2Only && !active.tp1Done && !active.tp1RearmRequired && c.low <= active.tp1) {
        const exitLots = Math.min(s.tp1Lots, active.tp1Active || s.tp1Lots);
        const isFirstTp1 = active.firstTp1Pending;
        exit(
          active,
          c,
          active.tp1,
          exitLots,
          isFirstTp1
            ? { entryTime: active.tp1LegEntryTime, entryType: active.tp1LegEntryType, entryLots: s.tp1Lots + s.tp2Lots }
            : { entryTime: active.tp1LegEntryTime, entryType: active.tp1LegEntryType, entryLots: active.tp1Active },
          "TP1",
          isFirstTp1
            ? `TP1 hit. ${exitLots} of ${s.tp1Lots + s.tp2Lots} lots booked at TP1; ${s.tp2Lots} lots held for TP2 from ${active.tp2LegEntryTime} entry.`
            : `TP1 hit. ${exitLots} refill lots (entered ${active.tp1LegEntryTime}) booked at TP1.`,
        );
        if (active.firstTp1Pending) {
          active.tp2Held = s.tp2Lots;
          active.tp1Active = 0;
          active.firstTp1Pending = false;
        } else {
          active.tp1Active = 0;
        }
        active.tp1Done = true;
        active.refillArmed = true;
        active.tp1RearmRequired = true;
      }
      if (active.refillArmed && c.high >= active.entry && active.tp1Active === 0 && active.tp2Held === s.tp2Lots) {
        applyRefill(active, c);
      }
      if (c.low <= active.tp2 && active.tp2Held > 0) {
        const exitLots = active.tp2Held;
        exit(
          active,
          c,
          active.tp2,
          exitLots,
          { entryTime: active.tp2LegEntryTime, entryType: "TP2_REMAINING", entryLots: exitLots },
          "TP2",
          `TP2 hit. ${exitLots} remaining TP2 lots (held since ${active.tp2LegEntryType.replaceAll("_", " ")} at ${active.tp2LegEntryTime}) closed at TP2.`,
        );
        active.tp2Held = 0;
        if (active.tp1Active <= 0) {
          pullbackWatch = { side: "PUT", tp1: active.tp1, tp2: active.tp2, sl: slForSide("PUT") };
          active = null;
          putCompleted = true;
        }
      }
    }
  }
  if (active && candles.length) {
    const last = candles[candles.length - 1];
    if (active.tp1Active > 0) {
      const refill = active.tp1LegEntryType === "TP1_REFILL";
      exit(
        active,
        last,
        last.close,
        active.tp1Active,
        { entryTime: active.tp1LegEntryTime, entryType: active.tp1LegEntryType, entryLots: active.tp1Active },
        "SESSION_END",
        refill
          ? `Session end square-off. ${active.tp1Active} refill lots (entered ${active.tp1LegEntryTime}) closed.`
          : `Session end square-off. ${active.tp1Active} lots from ${active.tp1LegEntryType.replaceAll("_", " ")} entry at ${active.tp1LegEntryTime} closed.`,
      );
    }
    if (active.tp2Held > 0) {
      exit(
        active,
        last,
        last.close,
        active.tp2Held,
        { entryTime: active.tp2LegEntryTime, entryType: "TP2_REMAINING", entryLots: active.tp2Held },
        "SESSION_END",
        `Session end square-off. ${active.tp2Held} remaining TP2 lots (held since ${active.tp2LegEntryType.replaceAll("_", " ")} at ${active.tp2LegEntryTime}).`,
      );
    }
  }
  return {
    trades,
    adaptiveHigh,
    adaptiveLow,
    finalCallTrigger: callTrigger(),
    finalPutTrigger: putTrigger(),
    events,
  };
}
