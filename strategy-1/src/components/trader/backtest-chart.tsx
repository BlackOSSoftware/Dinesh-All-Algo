"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";

type Candle = { time: string; open: number; high: number; low: number; close: number };
type Side = "CALL" | "PUT";
type Trade = {
  id: number;
  tradeDate: string;
  side: Side;
  entryTime: string;
  exitTime: string;
  entry: number;
  exit: number;
  entryLots: number;
  exitLots: number;
  entryType: string;
  reason: string;
  note?: string;
};

type BacktestEvent = {
  id: number;
  tradeDate: string;
  time: string;
  type: "BASE" | "NEW_HIGH" | "NEW_LOW" | "ENTRY";
  price: number;
  side?: Side;
  source: string;
};

type BacktestChartProps = {
  candles: Candle[];
  trades: Trade[];
  events?: BacktestEvent[];
  base?: number;
  upper?: number;
  lower?: number;
};

type Marker = {
  key: string;
  kind: "BUY" | "SELL";
  idx: number;
  price: number;
  time: string;
  tradeDate: string;
  label: string;
  detail: string;
  note?: string;
  side: Side;
  tradeId: number;
  reason?: string;
  entryType?: string;
};

const shortTime = (s: string) => s.replace("T", " ").slice(11, 16) || s.slice(0, 5);
const fmtPx = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n));

function buildCandleIndex(candles: Candle[]) {
  const exact = new Map<string, number>();
  const byDate = new Map<string, { times: string[]; indexes: number[] }>();
  candles.forEach((c, i) => {
    const raw = c.time.replace("T", " ");
    const date = raw.slice(0, 10);
    const t = shortTime(c.time);
    exact.set(`${date}|${t}`, i);
    const rows = byDate.get(date);
    if (rows) {
      rows.times.push(t);
      rows.indexes.push(i);
    } else {
      byDate.set(date, { times: [t], indexes: [i] });
    }
  });
  return { exact, byDate };
}

function indexedCandleIndex(index: ReturnType<typeof buildCandleIndex>, candles: Candle[], tradeDate: string, time: string) {
  const hit = index.exact.get(`${tradeDate}|${time}`);
  if (hit != null) return hit;
  const day = index.byDate.get(tradeDate);
  if (!day) return Math.max(0, candles.length - 1);
  const next = day.times.findIndex((t) => t >= time);
  return next >= 0 ? day.indexes[next] : day.indexes[day.indexes.length - 1];
}

function entryTypeText(t: string) {
  return t.replaceAll("_", " ");
}

function reasonColor(reason: string) {
  if (reason === "TP1") return "#2563eb";
  if (reason === "TP2") return "#16a34a";
  if (reason === "SL") return "#dc2626";
  return "#d97706";
}

function buildMarkers(trades: Trade[], candles: Candle[]): Marker[] {
  const candleLookup = buildCandleIndex(candles);
  const out: Marker[] = [];
  for (const t of trades) {
    if (t.entryType !== "TP2_REMAINING") {
      out.push({
        key: `buy-${t.id}`,
        kind: "BUY",
        idx: indexedCandleIndex(candleLookup, candles, t.tradeDate, t.entryTime),
        price: t.entry,
        time: t.entryTime,
        tradeDate: t.tradeDate,
        label: `Buy ${t.entryLots}L`,
        detail: `#${t.id} ${entryTypeText(t.entryType)} ${t.side} ${t.entryLots}L @ ${fmtPx(t.entry)}`,
        note: t.note,
        side: t.side,
        tradeId: t.id,
        entryType: t.entryType,
      });
    }
    out.push({
      key: `sell-${t.id}`,
      kind: "SELL",
      idx: indexedCandleIndex(candleLookup, candles, t.tradeDate, t.exitTime),
      price: t.exit,
      time: t.exitTime,
      tradeDate: t.tradeDate,
      label: `${t.reason} ${t.exitLots}L`,
      detail: `#${t.id} ${t.reason} ${t.side} ${t.exitLots}L @ ${fmtPx(t.exit)}`,
      note: t.note,
      side: t.side,
      tradeId: t.id,
      reason: t.reason,
      entryType: t.entryType,
    });
  }
  return out;
}

function buildVisibleTradeLines(trades: Trade[], candles: Candle[], start: number, end: number) {
  const candleLookup = buildCandleIndex(candles);
  return trades
    .map((t) => ({
      trade: t,
      entryIdx: indexedCandleIndex(candleLookup, candles, t.tradeDate, t.entryTime),
      exitIdx: indexedCandleIndex(candleLookup, candles, t.tradeDate, t.exitTime),
    }))
    .filter((x) => x.exitIdx >= start && x.entryIdx <= end);
}

function buildVisibleEntryEvents(events: BacktestEvent[], candles: Candle[], start: number, end: number) {
  const candleLookup = buildCandleIndex(candles);
  return events
    .filter((e) => e.type === "ENTRY")
    .map((e) => ({ ...e, idx: indexedCandleIndex(candleLookup, candles, e.tradeDate, e.time) }))
    .filter((e) => e.idx >= start && e.idx <= end);
}

function IconButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="grid h-8 w-8 place-items-center rounded-md border border-[var(--border-subtle)] bg-[var(--surface-elevated)] text-[var(--text-secondary)] hover:text-[var(--accent)]"
    >
      {children}
    </button>
  );
}

export function BacktestChart(props: BacktestChartProps) {
  const first = props.candles[0]?.time ?? "empty";
  const last = props.candles[props.candles.length - 1]?.time ?? "empty";
  const key = `${props.candles.length}-${first}-${last}-${props.trades.length}`;
  return <InteractiveBacktestChart key={key} {...props} />;
}

function InteractiveBacktestChart({
  candles,
  trades,
  events = [],
  base,
  upper,
  lower,
}: BacktestChartProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ x: number; start: number; end: number } | null>(null);
  const [view, setView] = useState({ start: 0, end: Math.max(0, candles.length - 1) });
  const [activeKey, setActiveKey] = useState<string | null>(null);

  const markers = useMemo(() => buildMarkers(trades, candles), [trades, candles]);

  const layout = useMemo(() => {
    if (!candles.length) return null;

    const w = 1160;
    const h = 520;
    const padL = 64;
    const padR = 72;
    const padT = 24;
    const padB = 38;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    const start = clamp(Math.floor(view.start), 0, Math.max(0, candles.length - 1));
    const end = clamp(Math.ceil(view.end), start + 1, Math.max(1, candles.length - 1));
    const visibleCandles = candles.slice(start, end + 1);
    const visibleMarkers = markers.filter((m) => m.idx >= start && m.idx <= end);
    const visibleTradeLines = buildVisibleTradeLines(trades, candles, start, end);
    const visibleEntryEvents = buildVisibleEntryEvents(events, candles, start, end);

    const prices: number[] = [];
    for (const c of visibleCandles) prices.push(c.high, c.low);
    for (const m of visibleMarkers) prices.push(m.price);
    for (const e of visibleEntryEvents) prices.push(e.price);
    if (base && visibleCandles.length) prices.push(base);
    if (upper && visibleCandles.length) prices.push(upper);
    if (lower && visibleCandles.length) prices.push(lower);

    const rawMin = Math.min(...prices);
    const rawMax = Math.max(...prices);
    const span = Math.max(1, rawMax - rawMin);
    const min = rawMin - span * 0.08;
    const max = rawMax + span * 0.1;
    const denom = Math.max(1, end - start);
    const xAt = (i: number) => padL + ((i - start) / denom) * plotW;
    const yAt = (p: number) => padT + ((max - p) / (max - min)) * plotH;
    const candleW = clamp((plotW / Math.max(1, visibleCandles.length)) * 0.58, 2.4, 11);

    return { w, h, padL, padR, padT, padB, plotW, plotH, start, end, visibleCandles, visibleMarkers, visibleTradeLines, visibleEntryEvents, min, max, xAt, yAt, candleW };
  }, [candles, markers, trades, events, base, upper, lower, view]);

  const zoom = (factor: number, anchor = 0.5) => {
    setView((v) => {
      const maxIdx = Math.max(0, candles.length - 1);
      const width = Math.max(12, (v.end - v.start) * factor);
      const center = v.start + (v.end - v.start) * anchor;
      let start = center - width * anchor;
      let end = center + width * (1 - anchor);
      if (start < 0) {
        end -= start;
        start = 0;
      }
      if (end > maxIdx) {
        start -= end - maxIdx;
        end = maxIdx;
      }
      return { start: clamp(start, 0, maxIdx), end: clamp(end, 0, maxIdx) };
    });
  };

  const pan = (ratio: number) => {
    setView((v) => {
      const maxIdx = Math.max(0, candles.length - 1);
      const width = v.end - v.start;
      const shift = width * ratio;
      let start = v.start + shift;
      let end = v.end + shift;
      if (start < 0) {
        end -= start;
        start = 0;
      }
      if (end > maxIdx) {
        start -= end - maxIdx;
        end = maxIdx;
      }
      return { start: clamp(start, 0, maxIdx), end: clamp(end, 0, maxIdx) };
    });
  };

  if (!candles.length || !layout) {
    return (
      <div className="grid h-[520px] place-items-center rounded-lg border border-[var(--border-subtle)] text-sm text-[var(--text-muted)]">
        Load candles to show chart
      </div>
    );
  }

  const { w, h, padL, padT, padB, plotW, plotH, start, end, visibleCandles, visibleMarkers, visibleTradeLines, visibleEntryEvents, min, max, xAt, yAt, candleW } = layout;
  const yTicks = 7;
  const activeMarker = visibleMarkers.find((m) => m.key === activeKey) ?? null;
  const rangeText = `${shortTime(candles[start]?.time ?? "")} - ${shortTime(candles[end]?.time ?? "")}`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-4 text-[10px] text-[var(--text-muted)]">
          <span className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" /> Up</span>
          <span className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-rose-500" /> Down</span>
          <span className="inline-flex items-center gap-1.5 text-emerald-600">▲ Buy</span>
          <span className="inline-flex items-center gap-1.5 text-blue-600">● TP1</span>
          <span className="inline-flex items-center gap-1.5 text-emerald-600">● TP2</span>
          <span className="inline-flex items-center gap-1.5 text-rose-600">● SL</span>
          <span className="font-mono">{visibleCandles.length} visible · {rangeText}</span>
        </div>
        <div className="flex items-center gap-1">
          <IconButton title="Pan left" onClick={() => pan(-0.35)}><ChevronLeft className="h-4 w-4" /></IconButton>
          <IconButton title="Zoom out" onClick={() => zoom(1.35)}><Minus className="h-4 w-4" /></IconButton>
          <IconButton title="Zoom in" onClick={() => zoom(0.65)}><Plus className="h-4 w-4" /></IconButton>
          <IconButton title="Pan right" onClick={() => pan(0.35)}><ChevronRight className="h-4 w-4" /></IconButton>
          <IconButton title="Show full chart" onClick={() => setView({ start: 0, end: Math.max(0, candles.length - 1) })}><Maximize2 className="h-4 w-4" /></IconButton>
          <IconButton title="Reset selection" onClick={() => setActiveKey(null)}><RotateCcw className="h-4 w-4" /></IconButton>
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)]">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${w} ${h}`}
          className="h-[520px] w-full cursor-grab select-none touch-none"
          onWheel={(e) => {
            e.preventDefault();
            const rect = svgRef.current?.getBoundingClientRect();
            const anchor = rect ? clamp((e.clientX - rect.left) / rect.width, 0.05, 0.95) : 0.5;
            zoom(e.deltaY > 0 ? 1.18 : 0.82, anchor);
          }}
          onPointerDown={(e) => {
            dragRef.current = { x: e.clientX, start: view.start, end: view.end };
            e.currentTarget.setPointerCapture(e.pointerId);
            e.currentTarget.style.cursor = "grabbing";
          }}
          onPointerMove={(e) => {
            const drag = dragRef.current;
            if (!drag || !svgRef.current) return;
            const rect = svgRef.current.getBoundingClientRect();
            const dx = e.clientX - drag.x;
            const shift = -(dx / Math.max(1, rect.width)) * (drag.end - drag.start);
            const maxIdx = Math.max(0, candles.length - 1);
            let ns = drag.start + shift;
            let ne = drag.end + shift;
            if (ns < 0) {
              ne -= ns;
              ns = 0;
            }
            if (ne > maxIdx) {
              ns -= ne - maxIdx;
              ne = maxIdx;
            }
            setView({ start: clamp(ns, 0, maxIdx), end: clamp(ne, 0, maxIdx) });
          }}
          onPointerUp={(e) => {
            dragRef.current = null;
            e.currentTarget.style.cursor = "grab";
          }}
          onPointerLeave={(e) => {
            dragRef.current = null;
            e.currentTarget.style.cursor = "grab";
          }}
        >
          <rect x={padL} y={padT} width={plotW} height={plotH} fill="transparent" />

          {Array.from({ length: yTicks + 1 }, (_, i) => {
            const p = min + ((max - min) * i) / yTicks;
            const y = yAt(p);
            return (
              <g key={i}>
                <line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="var(--border-subtle)" strokeWidth="1" strokeDasharray="4 5" />
                <text x={padL - 7} y={y + 3} textAnchor="end" fontSize="10" fill="var(--text-muted)" fontFamily="monospace">{fmtPx(p)}</text>
              </g>
            );
          })}

          {[
            { value: base, label: "BASE", color: "#6366f1" },
            { value: upper, label: "UPPER", color: "#10b981" },
            { value: lower, label: "LOWER", color: "#f43f5e" },
          ].map((line) =>
            line.value != null && line.value > min && line.value < max ? (
              <g key={line.label}>
                <line x1={padL} y1={yAt(line.value)} x2={padL + plotW} y2={yAt(line.value)} stroke={line.color} strokeWidth="1.2" strokeDasharray="7 5" />
                <text x={padL + plotW + 8} y={yAt(line.value) + 3} fontSize="9" fill={line.color} fontWeight="700">{line.label}</text>
              </g>
            ) : null,
          )}

          {visibleCandles.map((c, offset) => {
            const i = start + offset;
            const cx = xAt(i);
            const up = c.close >= c.open;
            const color = up ? "#10b981" : "#f43f5e";
            const bodyTop = yAt(Math.max(c.open, c.close));
            const bodyBottom = yAt(Math.min(c.open, c.close));
            const bodyH = Math.max(1.4, bodyBottom - bodyTop);
            return (
              <g key={c.time + i}>
                <line x1={cx} y1={yAt(c.high)} x2={cx} y2={yAt(c.low)} stroke={color} strokeWidth="1.2" />
                <rect x={cx - candleW / 2} y={bodyTop} width={candleW} height={bodyH} fill={color} rx="0.5" />
              </g>
            );
          })}

          {visibleTradeLines.map(({ trade, entryIdx, exitIdx }) => {
            const x1 = xAt(clamp(entryIdx, start, end));
            const x2 = xAt(clamp(exitIdx, start, end));
            const y1 = yAt(trade.entry);
            const y2 = yAt(trade.exit);
            const color = reasonColor(trade.reason);
            return (
              <g key={`line-${trade.id}`}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth="1.8" opacity="0.52" />
                <circle cx={x1} cy={y1} r="3.2" fill={trade.side === "CALL" ? "#059669" : "#e11d48"} stroke="#fff" />
                <circle cx={x2} cy={y2} r="3.8" fill={color} stroke="#fff" />
              </g>
            );
          })}

          {visibleEntryEvents.map((e) => {
            const x = xAt(e.idx);
            const y = yAt(e.price);
            const color = e.side === "CALL" ? "#059669" : "#e11d48";
            const isSwitch = /SL switch/i.test(e.source);
            const isRe = /retrace|pullback/i.test(e.source);
            return (
              <g
                key={`event-${e.tradeDate}-${e.id}`}
                onPointerEnter={() => setActiveKey(`event-${e.tradeDate}-${e.id}`)}
                onClick={(ev) => {
                  ev.stopPropagation();
                  setActiveKey(`event-${e.tradeDate}-${e.id}`);
                }}
                className="cursor-pointer"
              >
                <rect x={x - 21} y={y - 26} width="42" height="13" rx="3" fill={isSwitch ? "#dc2626" : isRe ? "#7c3aed" : color} opacity="0.95" />
                <text x={x} y={y - 16.5} textAnchor="middle" fontSize="7.5" fill="#fff" fontWeight="700">
                  {isSwitch ? "SWITCH" : isRe ? "RE-ENTRY" : "ENTRY"}
                </text>
                <line x1={x} y1={y - 12} x2={x} y2={y - 2} stroke={isSwitch ? "#dc2626" : color} strokeWidth="1.2" />
              </g>
            );
          })}

          {visibleMarkers.map((m) => {
            const x = xAt(m.idx);
            const y = yAt(m.price);
            const fill = m.kind === "BUY" ? (m.side === "CALL" ? "#059669" : "#e11d48") : reasonColor(m.reason ?? "");
            const selected = m.key === activeKey;
            const aw = selected ? 12 : 9;
            const ah = selected ? 14 : 11;
            const badgeY = m.kind === "BUY" ? y - 30 - ((m.tradeId % 3) * 15) : y + 22 + ((m.tradeId % 3) * 15);
            return (
              <g
                key={m.key}
                onPointerEnter={() => setActiveKey(m.key)}
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveKey(m.key);
                }}
                className="cursor-pointer"
              >
                {m.kind === "BUY" ? (
                  <polygon points={`${x},${y - ah} ${x - aw / 2},${y - 1} ${x + aw / 2},${y - 1}`} fill={fill} stroke="#fff" strokeWidth="1" />
                ) : (
                  <polygon points={`${x},${y + ah} ${x - aw / 2},${y + 1} ${x + aw / 2},${y + 1}`} fill={fill} stroke="#fff" strokeWidth="1" />
                )}
                {selected ? <circle cx={x} cy={y} r="16" fill={fill} opacity="0.08" /> : null}
                <rect x={x - 28} y={badgeY - 9} width="56" height="14" rx="3" fill="var(--surface-elevated)" stroke={fill} strokeWidth="0.7" opacity="0.96" />
                <text x={x} y={badgeY + 1} textAnchor="middle" fontSize="7.5" fill={fill} fontWeight="700">
                  {m.kind === "BUY" ? `#${m.tradeId} ${m.entryType === "TP1_REFILL" ? "REFILL" : m.entryType === "TP2_PULLBACK" ? "RE" : "BUY"}` : `#${m.tradeId} ${m.reason}`}
                </text>
              </g>
            );
          })}

          {activeKey?.startsWith("event-") ? (() => {
            const event = visibleEntryEvents.find((e) => `event-${e.tradeDate}-${e.id}` === activeKey);
            if (!event) return null;
            const x = xAt(event.idx);
            const y = yAt(event.price);
            const boxW = 290;
            const boxH = 58;
            const bx = clamp(x - boxW / 2, padL + 4, padL + plotW - boxW - 4);
            const by = clamp(y - boxH - 32, padT + 4, padT + plotH - boxH - 4);
            return (
              <g>
                <rect x={bx} y={by} width={boxW} height={boxH} rx="5" fill="var(--surface-elevated)" stroke="var(--border-subtle)" />
                <text x={bx + 10} y={by + 16} fontSize="11" fill="var(--text-primary)" fontWeight="700">{event.side} entry @ {fmtPx(event.price)}</text>
                <text x={bx + 10} y={by + 32} fontSize="10" fill="var(--text-muted)" fontFamily="monospace">{event.tradeDate} {event.time}</text>
                <text x={bx + 10} y={by + 47} fontSize="9" fill="var(--text-secondary)">{event.source.slice(0, 58)}</text>
              </g>
            );
          })() : activeMarker ? (() => {
            const x = xAt(activeMarker.idx);
            const y = yAt(activeMarker.price);
            const boxW = 300;
            const boxH = activeMarker.note ? 66 : 48;
            const bx = clamp(x - boxW / 2, padL + 4, padL + plotW - boxW - 4);
            const by = clamp(y - boxH - 18, padT + 4, padT + plotH - boxH - 4);
            return (
              <g>
                <line x1={x} y1={padT} x2={x} y2={padT + plotH} stroke="var(--text-muted)" strokeDasharray="3 4" opacity="0.35" />
                <line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="var(--text-muted)" strokeDasharray="3 4" opacity="0.35" />
                <rect x={bx} y={by} width={boxW} height={boxH} rx="5" fill="var(--surface-elevated)" stroke="var(--border-subtle)" />
                <text x={bx + 10} y={by + 16} fontSize="11" fill="var(--text-primary)" fontWeight="700">{activeMarker.detail}</text>
                <text x={bx + 10} y={by + 32} fontSize="10" fill="var(--text-muted)" fontFamily="monospace">
                  {activeMarker.tradeDate} {activeMarker.time}
                </text>
                {activeMarker.note ? (
                  <text x={bx + 10} y={by + 49} fontSize="9" fill="var(--text-secondary)">
                    {activeMarker.note.slice(0, 70)}
                  </text>
                ) : null}
              </g>
            );
          })() : null}

          {visibleCandles
            .map((c, offset, arr) => {
              const i = start + offset;
              const step = Math.max(1, Math.ceil(arr.length / 8));
              return offset === 0 || offset === arr.length - 1 || offset % step === 0 ? { i, t: shortTime(c.time) } : null;
            })
            .filter((x): x is { i: number; t: string } => x != null)
            .map(({ i, t }) => (
              <text key={`${t}-${i}`} x={xAt(i)} y={h - 12} textAnchor="middle" fontSize="10" fill="var(--text-muted)" fontFamily="monospace">{t}</text>
            ))}

          <rect x={padL} y={padT} width={plotW} height={plotH} fill="none" stroke="var(--border-subtle)" />
          <text x={padL + 4} y={h - padB + 24} fontSize="9" fill="var(--text-muted)">Drag to pan · Mouse wheel to zoom · Click markers for details</text>
        </svg>
      </div>
    </div>
  );
}
