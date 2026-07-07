"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Minus, Plus, RotateCcw } from "lucide-react";
import type { BreakoutBacktestCandle, BreakoutBacktestTrade } from "@/lib/strategy3/types";
import { cn } from "@/components/ui";

export type ChartLevels = {
  premiumClose?: number | null;
  trigger?: number | null;
  target?: number | null;
  stop?: number | null;
};

type Props = {
  candles: BreakoutBacktestCandle[];
  trades?: BreakoutBacktestTrade[];
  levels?: ChartLevels;
  title?: string;
};

const fmtPx = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shortTime = (s: string) => s.replace("T", " ").slice(11, 16) || s.slice(0, 5);
const clamp = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n));

type Marker = {
  key: string;
  idx: number;
  price: number;
  kind: "ENTRY" | "EXIT";
  label: string;
  detail: string;
};

function buildCandleIndex(candles: BreakoutBacktestCandle[]) {
  const exact = new Map<string, number>();
  candles.forEach((c, i) => {
    exact.set(c.time, i);
    exact.set(c.time.replace("T", " "), i);
    exact.set(shortTime(c.time), i);
  });
  return exact;
}

function candleIndex(candles: BreakoutBacktestCandle[], timeRaw: string | undefined | null): number {
  if (!timeRaw || !candles.length) return 0;
  const lookup = buildCandleIndex(candles);
  const t = timeRaw.replace("T", " ");
  if (lookup.has(timeRaw)) return lookup.get(timeRaw)!;
  if (lookup.has(t)) return lookup.get(t)!;
  if (lookup.has(shortTime(timeRaw))) return lookup.get(shortTime(timeRaw))!;
  const st = shortTime(timeRaw);
  for (let i = 0; i < candles.length; i++) {
    if (shortTime(candles[i].time) >= st) return i;
  }
  return candles.length - 1;
}

function buildMarkers(candles: BreakoutBacktestCandle[], trades: BreakoutBacktestTrade[]): Marker[] {
  const out: Marker[] = [];
  for (const t of trades) {
    if (t.fillTime && t.entryPrice != null) {
      out.push({
        key: `e-${t.id}`,
        idx: candleIndex(candles, t.fillTime),
        price: t.entryPrice,
        kind: "ENTRY",
        label: "Entry",
        detail: `${t.sideLabel ?? t.side} @ ${fmtPx(t.entryPrice)}`,
      });
    }
    if (t.exitTime && t.exitPrice != null) {
      out.push({
        key: `x-${t.id}`,
        idx: candleIndex(candles, t.exitTime),
        price: t.exitPrice,
        kind: "EXIT",
        label: t.exitReason ?? "Exit",
        detail: `${t.exitReason ?? "Exit"} @ ${fmtPx(t.exitPrice)} · ${fmtPx(t.points ?? t.pnl ?? 0)} pts`,
      });
    }
  }
  return out;
}

function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: React.ReactNode }) {
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

export function BreakoutBacktestChart({ candles, trades = [], levels, title }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [view, setView] = useState({ start: 0, end: Math.max(0, candles.length - 1) });
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [yShift, setYShift] = useState(0);

  const markers = useMemo(() => buildMarkers(candles, trades), [candles, trades]);

  const layout = useMemo(() => {
    if (!candles.length) return null;
    const w = 1160;
    const h = 480;
    const padL = 64;
    const padR = 120;
    const padT = 28;
    const padB = 40;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    const start = clamp(Math.floor(view.start), 0, Math.max(0, candles.length - 1));
    const end = clamp(Math.ceil(view.end), start + 1, Math.max(1, candles.length - 1));
    const visibleCandles = candles.slice(start, end + 1);
    const visibleMarkers = markers.filter((m) => m.idx >= start && m.idx <= end);

    const prices: number[] = [];
    for (const c of visibleCandles) prices.push(c.high, c.low);
    for (const m of visibleMarkers) prices.push(m.price);
    if (levels?.premiumClose) prices.push(levels.premiumClose);
    if (levels?.trigger) prices.push(levels.trigger);
    if (levels?.target) prices.push(levels.target);
    if (levels?.stop) prices.push(levels.stop);

    const rawMin = Math.min(...prices);
    const rawMax = Math.max(...prices);
    const span = Math.max(1, rawMax - rawMin);
    const shift = yShift * span * 0.15;
    const min = Math.max(0, rawMin - span * 0.1 - shift);
    const max = rawMax + span * 0.12 - shift;
    const denom = Math.max(1, end - start);
    const xAt = (i: number) => padL + ((i - start) / denom) * plotW;
    const yAt = (p: number) => padT + ((max - p) / (max - min)) * plotH;
    const candleW = clamp((plotW / Math.max(1, visibleCandles.length)) * 0.58, 2.4, 12);

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
  }, [candles, markers, levels, view, yShift]);

  const zoom = (factor: number, anchor = 0.5) => {
    setView((v) => {
      const maxIdx = Math.max(0, candles.length - 1);
      const width = Math.max(8, (v.end - v.start) * factor);
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
      <div className="grid h-[480px] place-items-center rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-muted)] text-sm text-[var(--text-muted)]">
        Select an expiry day and leg to view option premium chart
      </div>
    );
  }

  const { w, h, padL, padT, padB, plotW, plotH, start, end, visibleCandles, visibleMarkers, min, max, xAt, yAt, candleW } =
    layout;
  const activeMarker = visibleMarkers.find((m) => m.key === activeKey) ?? null;
  const levelLines: { label: string; price: number; color: string }[] = [];
  if (levels?.premiumClose != null) levelLines.push({ label: "Base", price: levels.premiumClose, color: "#94a3b8" });
  if (levels?.trigger != null) levelLines.push({ label: "Trigger", price: levels.trigger, color: "#3b82f6" });
  if (levels?.target != null) levelLines.push({ label: "TP", price: levels.target, color: "#22c55e" });
  if (levels?.stop != null) levelLines.push({ label: "SL", price: levels.stop, color: "#ef4444" });

  return (
    <div className="space-y-2">
      {title ? <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p> : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-3 text-[10px] text-[var(--text-muted)]">
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-[var(--success)]" /> Up</span>
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-[var(--danger)]" /> Down</span>
          <span className="text-[var(--success)]">▲ Entry</span>
          <span className="text-[var(--danger)]">▼ Exit</span>
          {levelLines.map((l) => (
            <span key={l.label} style={{ color: l.color }}>— {l.label}</span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <IconButton title="Pan left" onClick={() => pan(-0.35)}><ChevronLeft className="h-4 w-4" /></IconButton>
          <IconButton title="Zoom out" onClick={() => zoom(1.35)}><Minus className="h-4 w-4" /></IconButton>
          <IconButton title="Zoom in" onClick={() => zoom(0.65)}><Plus className="h-4 w-4" /></IconButton>
          <IconButton title="Pan right" onClick={() => pan(0.35)}><ChevronRight className="h-4 w-4" /></IconButton>
          <IconButton title="Price up" onClick={() => setYShift((s) => s + 1)}><span className="text-xs font-bold">↑</span></IconButton>
          <IconButton title="Price down" onClick={() => setYShift((s) => s - 1)}><span className="text-xs font-bold">↓</span></IconButton>
          <IconButton title="Reset view" onClick={() => { setView({ start: 0, end: Math.max(0, candles.length - 1) }); setYShift(0); }}>
            <RotateCcw className="h-4 w-4" />
          </IconButton>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] p-2">
        <svg ref={svgRef} width={w} height={h} className="mx-auto block select-none">
          {[0, 1, 2, 3, 4, 5, 6].map((i) => {
            const p = min + ((max - min) * i) / 6;
            const y = yAt(p);
            return (
              <g key={i}>
                <line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="var(--border-subtle)" strokeDasharray="3 4" />
                <text x={padL - 6} y={y + 3} textAnchor="end" fontSize={9} fill="var(--text-muted)">{fmtPx(p)}</text>
              </g>
            );
          })}

          {levelLines.map((lv) => (
            <g key={lv.label}>
              <line x1={padL} y1={yAt(lv.price)} x2={padL + plotW} y2={yAt(lv.price)} stroke={lv.color} strokeWidth={1.2} strokeDasharray="6 4" opacity={0.85} />
              <text x={padL + plotW + 6} y={yAt(lv.price) + 3} fontSize={9} fill={lv.color}>{lv.label} {fmtPx(lv.price)}</text>
            </g>
          ))}

          {visibleCandles.map((c, vi) => {
            const idx = start + vi;
            const x = xAt(idx);
            const up = c.close >= c.open;
            const color = up ? "var(--success)" : "var(--danger)";
            return (
              <g key={`${c.time}-${idx}`}>
                <line x1={x} y1={yAt(c.high)} x2={x} y2={yAt(c.low)} stroke={color} strokeWidth={1} />
                <rect
                  x={x - candleW / 2}
                  y={Math.min(yAt(c.open), yAt(c.close))}
                  width={candleW}
                  height={Math.max(2, Math.abs(yAt(c.close) - yAt(c.open)))}
                  fill={color}
                  opacity={0.9}
                />
              </g>
            );
          })}

          {visibleMarkers.map((m) => {
            const x = xAt(m.idx);
            const y = yAt(m.price);
            const up = m.kind === "ENTRY";
            return (
              <g
                key={m.key}
                className="cursor-pointer"
                onMouseEnter={() => setActiveKey(m.key)}
                onMouseLeave={() => setActiveKey(null)}
              >
                <polygon
                  points={up ? `${x},${y - 8} ${x - 6},${y + 4} ${x + 6},${y + 4}` : `${x},${y + 8} ${x - 6},${y - 4} ${x + 6},${y - 4}`}
                  fill={up ? "var(--success)" : "var(--danger)"}
                />
              </g>
            );
          })}

          {visibleCandles.map((c, vi) => {
            if (vi % Math.max(1, Math.floor(visibleCandles.length / 7)) !== 0) return null;
            const idx = start + vi;
            return (
              <text key={`t-${idx}`} x={xAt(idx)} y={h - padB + 14} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
                {shortTime(c.time)}
              </text>
            );
          })}
        </svg>
      </div>

      <p className="text-xs text-[var(--text-muted)]">
        {visibleCandles.length} candles · {shortTime(candles[start]?.time ?? "")} – {shortTime(candles[end]?.time ?? "")} · Range {fmtPx(min)} – {fmtPx(max)}
        {activeMarker ? ` · ${activeMarker.detail}` : ""}
      </p>
    </div>
  );
}
