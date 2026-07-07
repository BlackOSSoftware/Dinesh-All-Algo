"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import type { GridBacktestCandle, GridBacktestTrade, GridLevelRow } from "@/lib/strategy2/types";
import { cn } from "@/components/ui";

export type GridBacktestChartProps = {
  candles: GridBacktestCandle[];
  trades: GridBacktestTrade[];
  gridLevels: GridLevelRow[];
  referencePrice?: number;
};

type Marker = {
  key: string;
  kind: "BUY" | "SELL";
  idx: number;
  price: number;
  time: string;
  date: string;
  label: string;
  detail: string;
  tradeId: number;
  action: string;
  level: string;
};

const shortTime = (s: string) => s.replace("T", " ").slice(11, 16) || s.slice(0, 5);
const fmtPx = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n));

function buildCandleIndex(candles: GridBacktestCandle[]) {
  const exact = new Map<string, number>();
  const byDate = new Map<string, { times: string[]; indexes: number[] }>();
  candles.forEach((c, i) => {
    const raw = c.time.replace("T", " ");
    const date = c.date || raw.slice(0, 10);
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

function indexedCandleIndex(
  index: ReturnType<typeof buildCandleIndex>,
  candles: GridBacktestCandle[],
  tradeDate: string,
  time: string,
) {
  const hit = index.exact.get(`${tradeDate}|${shortTime(time)}`);
  if (hit != null) return hit;
  const day = index.byDate.get(tradeDate);
  if (!day) return Math.max(0, candles.length - 1);
  const t = shortTime(time);
  const next = day.times.findIndex((x) => x >= t);
  return next >= 0 ? day.indexes[next] : day.indexes[day.indexes.length - 1];
}

function buildMarkers(trades: GridBacktestTrade[], candles: GridBacktestCandle[]): Marker[] {
  const lookup = buildCandleIndex(candles);
  return trades.map((t) => ({
    key: `t-${t.id}`,
    kind: t.side === "BUY" ? "BUY" : "SELL",
    idx: indexedCandleIndex(lookup, candles, t.date, t.time),
    price: t.fillPrice ?? t.price,
    time: t.time,
    date: t.date,
    label: `${t.side === "BUY" ? "Buy" : "Sell"} ${t.lots}L`,
    detail: `#${t.id} ${t.action.replaceAll("_", " ")} @ ${t.level} · Grid ${fmtPx(t.levelPrice || 0)} · Fill ${fmtPx(t.fillPrice ?? t.price)} · ${t.lots}L · Pos ${t.positionAfter}`,
    tradeId: t.id,
    action: t.action,
    level: t.level,
  }));
}

function actionColor(action: string) {
  if (action === "INITIAL_BUY" || action === "ADD" || action === "REENTER") return "var(--success)";
  if (action === "EXIT") return "var(--danger)";
  return "var(--accent)";
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

export function GridBacktestChart(props: GridBacktestChartProps) {
  const key = `${props.candles.length}-${props.trades.length}-${props.candles[0]?.time ?? ""}`;
  return <InteractiveGridBacktestChart key={key} {...props} />;
}

function InteractiveGridBacktestChart({
  candles,
  trades,
  gridLevels,
  referencePrice,
}: GridBacktestChartProps) {
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
    const padR = 88;
    const padT = 24;
    const padB = 42;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    const start = clamp(Math.floor(view.start), 0, Math.max(0, candles.length - 1));
    const end = clamp(Math.ceil(view.end), start + 1, Math.max(1, candles.length - 1));
    const visibleCandles = candles.slice(start, end + 1);
    const visibleMarkers = markers.filter((m) => m.idx >= start && m.idx <= end);

    const prices: number[] = [];
    for (const c of visibleCandles) prices.push(c.high, c.low);
    for (const m of visibleMarkers) prices.push(m.price);
    for (const g of gridLevels) prices.push(g.price);
    if (referencePrice) prices.push(referencePrice);

    const rawMin = Math.min(...prices);
    const rawMax = Math.max(...prices);
    const span = Math.max(1, rawMax - rawMin);
    const min = rawMin - span * 0.08;
    const max = rawMax + span * 0.1;
    const denom = Math.max(1, end - start);
    const xAt = (i: number) => padL + ((i - start) / denom) * plotW;
    const yAt = (p: number) => padT + ((max - p) / (max - min)) * plotH;
    const candleW = clamp((plotW / Math.max(1, visibleCandles.length)) * 0.58, 2.4, 11);

    return {
      w,
      h,
      padL,
      padR,
      padT,
      padB,
      plotW,
      plotH,
      start,
      end,
      visibleCandles,
      visibleMarkers,
      min,
      max,
      xAt,
      yAt,
      candleW,
    };
  }, [candles, markers, gridLevels, referencePrice, view]);

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
      <div className="grid h-[520px] place-items-center rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] text-sm text-[var(--text-muted)]">
        Run backtest to load chart
      </div>
    );
  }

  const {
    w,
    h,
    padL,
    padT,
    padB,
    plotW,
    plotH,
    start,
    end,
    visibleCandles,
    visibleMarkers,
    min,
    max,
    xAt,
    yAt,
    candleW,
  } = layout;
  const yTicks = 7;
  const activeMarker = visibleMarkers.find((m) => m.key === activeKey) ?? null;
  const rangeText = `${shortTime(candles[start]?.time ?? "")} – ${shortTime(candles[end]?.time ?? "")}`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-4 text-[10px] text-[var(--text-muted)]">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-[var(--success)]" /> Up
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-[var(--danger)]" /> Down
          </span>
          <span className="inline-flex items-center gap-1.5 text-[var(--success)]">▲ Buy / Add</span>
          <span className="inline-flex items-center gap-1.5 text-[var(--danger)]">▼ Exit</span>
          <span className="inline-flex items-center gap-1.5 text-[var(--accent)]">— Grid levels</span>
          <span className="font-mono">
            {visibleCandles.length} visible · {rangeText}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <IconButton title="Pan left" onClick={() => pan(-0.35)}>
            <ChevronLeft className="h-4 w-4" />
          </IconButton>
          <IconButton title="Zoom out" onClick={() => zoom(1.35)}>
            <Minus className="h-4 w-4" />
          </IconButton>
          <IconButton title="Zoom in" onClick={() => zoom(0.65)}>
            <Plus className="h-4 w-4" />
          </IconButton>
          <IconButton title="Pan right" onClick={() => pan(0.35)}>
            <ChevronRight className="h-4 w-4" />
          </IconButton>
          <IconButton
            title="Show full chart"
            onClick={() => setView({ start: 0, end: Math.max(0, candles.length - 1) })}
          >
            <Maximize2 className="h-4 w-4" />
          </IconButton>
          <IconButton title="Reset marker" onClick={() => setActiveKey(null)}>
            <RotateCcw className="h-4 w-4" />
          </IconButton>
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
          {Array.from({ length: yTicks + 1 }, (_, i) => {
            const p = min + ((max - min) * i) / yTicks;
            const y = yAt(p);
            return (
              <g key={i}>
                <line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="var(--border-subtle)" strokeWidth="1" strokeDasharray="4 5" />
                <text x={padL - 7} y={y + 3} textAnchor="end" fontSize="10" fill="var(--text-muted)" fontFamily="monospace">
                  {fmtPx(p)}
                </text>
              </g>
            );
          })}

          {gridLevels.map((g) => {
            const isBase = g.level === "BASE";
            const color = isBase ? "var(--accent)" : "var(--text-muted)";
            return (
              <g key={g.level}>
                <line
                  x1={padL}
                  y1={yAt(g.price)}
                  x2={padL + plotW}
                  y2={yAt(g.price)}
                  stroke={color}
                  strokeWidth={isBase ? 1.4 : 1}
                  strokeDasharray={isBase ? "0" : "7 5"}
                  opacity={isBase ? 1 : 0.75}
                />
                <text x={padL + plotW + 8} y={yAt(g.price) + 3} fontSize="9" fill={color} fontWeight={isBase ? "700" : "500"}>
                  {g.level} {fmtPx(g.price)}
                </text>
              </g>
            );
          })}

          {visibleCandles.map((c, offset) => {
            const i = start + offset;
            const cx = xAt(i);
            const up = c.close >= c.open;
            const color = up ? "var(--success)" : "var(--danger)";
            const bodyTop = yAt(Math.max(c.open, c.close));
            const bodyBottom = yAt(Math.min(c.open, c.close));
            const bodyH = Math.max(1.4, bodyBottom - bodyTop);
            return (
              <g key={`${c.time}-${i}`}>
                <line x1={cx} y1={yAt(c.high)} x2={cx} y2={yAt(c.low)} stroke={color} strokeWidth="1.2" />
                <rect x={cx - candleW / 2} y={bodyTop} width={candleW} height={bodyH} fill={color} rx="0.5" />
              </g>
            );
          })}

          {visibleMarkers.map((m) => {
            const x = xAt(m.idx);
            const y = yAt(m.price);
            const fill = actionColor(m.action);
            const selected = m.key === activeKey;
            const aw = selected ? 12 : 9;
            const ah = selected ? 14 : 11;
            const badgeY = m.kind === "BUY" ? y - 30 - ((m.tradeId % 3) * 14) : y + 22 + ((m.tradeId % 3) * 14);
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
                  <polygon
                    points={`${x},${y - ah} ${x - aw / 2},${y - 1} ${x + aw / 2},${y - 1}`}
                    fill={fill}
                    stroke="var(--surface-elevated)"
                    strokeWidth="1"
                  />
                ) : (
                  <polygon
                    points={`${x},${y + ah} ${x - aw / 2},${y + 1} ${x + aw / 2},${y + 1}`}
                    fill={fill}
                    stroke="var(--surface-elevated)"
                    strokeWidth="1"
                  />
                )}
                {selected ? <circle cx={x} cy={y} r="16" fill={fill} opacity="0.1" /> : null}
                <rect
                  x={x - 30}
                  y={badgeY - 9}
                  width="60"
                  height="14"
                  rx="3"
                  fill="var(--surface-elevated)"
                  stroke={fill}
                  strokeWidth="0.7"
                  opacity="0.96"
                />
                <text x={x} y={badgeY + 1} textAnchor="middle" fontSize="7.5" fill={fill} fontWeight="700">
                  {m.kind === "BUY" ? `#${m.tradeId} BUY` : `#${m.tradeId} EXIT`}
                </text>
              </g>
            );
          })}

          {activeMarker
            ? (() => {
                const x = xAt(activeMarker.idx);
                const y = yAt(activeMarker.price);
                const boxW = 320;
                const boxH = 56;
                const bx = clamp(x - boxW / 2, padL + 4, padL + plotW - boxW - 4);
                const by = clamp(y - boxH - 18, padT + 4, padT + plotH - boxH - 4);
                return (
                  <g>
                    <line x1={x} y1={padT} x2={x} y2={padT + plotH} stroke="var(--text-muted)" strokeDasharray="3 4" opacity="0.35" />
                    <line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="var(--text-muted)" strokeDasharray="3 4" opacity="0.35" />
                    <rect x={bx} y={by} width={boxW} height={boxH} rx="5" fill="var(--surface-elevated)" stroke="var(--border-subtle)" />
                    <text x={bx + 10} y={by + 16} fontSize="11" fill="var(--text-primary)" fontWeight="700">
                      {activeMarker.detail}
                    </text>
                    <text x={bx + 10} y={by + 32} fontSize="10" fill="var(--text-muted)" fontFamily="monospace">
                      {activeMarker.date} {shortTime(activeMarker.time)}
                    </text>
                    <text x={bx + 10} y={by + 47} fontSize="9" fill="var(--text-secondary)">
                      Level {activeMarker.level} · {activeMarker.action.replaceAll("_", " ")}
                    </text>
                  </g>
                );
              })()
            : null}

          {visibleCandles
            .map((c, offset, arr) => {
              const i = start + offset;
              const step = Math.max(1, Math.ceil(arr.length / 10));
              return offset === 0 || offset === arr.length - 1 || offset % step === 0 ? { i, t: shortTime(c.time) } : null;
            })
            .filter((x): x is { i: number; t: string } => x != null)
            .map(({ i, t }) => (
              <text key={`${t}-${i}`} x={xAt(i)} y={h - 12} textAnchor="middle" fontSize="10" fill="var(--text-muted)" fontFamily="monospace">
                {t}
              </text>
            ))}

          <rect x={padL} y={padT} width={plotW} height={plotH} fill="none" stroke="var(--border-subtle)" />
          <text x={padL + 4} y={h - padB + 24} fontSize="9" fill="var(--text-muted)">
            Drag to pan · Mouse wheel to zoom · Click markers for trade details
          </text>
        </svg>
      </div>
    </div>
  );
}
