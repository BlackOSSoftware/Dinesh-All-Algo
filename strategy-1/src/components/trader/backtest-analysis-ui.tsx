"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Minus,
  Plus,
  RotateCcw,
  Search,
} from "lucide-react";
import { cn } from "@/components/ui";
import {
  type ChartCandle,
  type CycleTradeRecord,
  type DayDetail,
  type DaySummaryRow,
  type NetBreakdown,
  type PlannedLevel,
  type TimelineEvent,
  fmtDate,
  fmtPx,
  levelTypeLabel,
} from "@/lib/backtest-trend-analysis";
import { BtCard } from "@/components/trader/backtest-premium-ui";

/* ─── Base & Trigger ─── */

export function BaseTriggerSection({ rows }: { rows: DaySummaryRow[] }) {
  const [selected, setSelected] = useState(rows[0]?.date ?? "");
  useEffect(() => {
    if (rows.length && !rows.find((r) => r.date === selected)) setSelected(rows[0].date);
  }, [rows, selected]);

  const sel = rows.find((r) => r.date === selected);

  return (
    <BtCard>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Base & Trigger Levels</h3>
        <p className="text-xs text-[var(--text-muted)]">Date-wise base from 09:15 close and planned entry triggers</p>
      </div>
      <div className="overflow-auto rounded-lg border border-[var(--border-subtle)]">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="sticky top-0 bg-[var(--surface-elevated)] text-[var(--text-muted)]">
            <tr>
              {["Date", "Base", "Call Trigger (+)", "Put Trigger (−)", "Trades", "Net Pts"].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.date}
                onClick={() => setSelected(r.date)}
                className={cn(
                  "cursor-pointer border-t border-white/[0.04] transition hover:bg-white/[0.03]",
                  selected === r.date && "bg-teal-500/10",
                )}
              >
                <td className="px-3 py-2 font-medium text-[var(--text-secondary)]">{fmtDate(r.date)}</td>
                <td className="px-3 py-2 font-mono text-amber-400">{fmtPx(r.base)}</td>
                <td className="px-3 py-2 font-mono text-emerald-400">{fmtPx(r.callTrigger)}</td>
                <td className="px-3 py-2 font-mono text-rose-400">{fmtPx(r.putTrigger)}</td>
                <td className="px-3 py-2">{r.trades}</td>
                <td className={cn("px-3 py-2 font-mono font-semibold", r.points >= 0 ? "text-emerald-400" : "text-rose-400")}>
                  {r.points}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sel ? (
        <div className="mt-3 grid gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] p-3 sm:grid-cols-3">
          <div>
            <p className="text-[10px] uppercase text-[var(--text-muted)]">Selected Day</p>
            <p className="font-mono text-sm text-[var(--text-secondary)]">{fmtDate(sel.date)}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-[var(--text-muted)]">Range Width</p>
            <p className="font-mono text-sm text-teal-400">{fmtPx(sel.callTrigger - sel.base)} pts each side</p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-[var(--text-muted)]">Day P&L</p>
            <p className={cn("font-mono text-sm font-semibold", sel.points >= 0 ? "text-emerald-400" : "text-rose-400")}>{sel.points} pts</p>
          </div>
        </div>
      ) : null}
    </BtCard>
  );
}

/* ─── Adaptive Timeline ─── */

export function AdaptiveTimelineSection({
  dayDetails,
  selectedDate,
  onSelectDate,
}: {
  dayDetails: DayDetail[];
  selectedDate: string;
  onSelectDate: (d: string) => void;
}) {
  const day = dayDetails.find((d) => d.date === selectedDate) ?? dayDetails[0];
  const events = day?.timeline ?? [];

  return (
    <BtCard>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Strategy Timeline</h3>
          <p className="text-xs text-[var(--text-muted)]">When base, entries, averaging, TP1, TP2 & re-entry fired</p>
        </div>
        <select
          className="h-9 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-3 text-xs text-[var(--text-secondary)]"
          value={day?.date ?? ""}
          onChange={(e) => onSelectDate(e.target.value)}
        >
          {dayDetails.map((d) => (
            <option key={d.date} value={d.date}>{fmtDate(d.date)}</option>
          ))}
        </select>
      </div>
      <div className="relative max-h-[360px] overflow-auto pl-4">
        <div className="absolute bottom-0 left-[7px] top-0 w-px bg-white/10" />
        <div className="space-y-3">
          {events.map((ev, i) => (
            <TimelineItem key={`${ev.time}-${ev.event}-${i}`} event={ev} />
          ))}
          {!events.length ? <p className="text-xs text-[var(--text-muted)]">No events for this day.</p> : null}
        </div>
      </div>
    </BtCard>
  );
}

function TimelineItem({ event }: { event: TimelineEvent }) {
  const dotColor =
    event.event.includes("BASE") ? "bg-amber-400" :
    event.event.includes("ENTRY") || event.event === "REENTRY" ? "bg-teal-400" :
    event.event.includes("TP1") ? "bg-blue-400" :
    event.event.includes("SL") ? "bg-rose-500" :
    event.event.includes("TP2") || event.event.includes("EXIT") ? "bg-violet-400" :
    "bg-slate-500";

  return (
    <div className="relative flex gap-3">
      <span className={cn("relative z-10 mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-[#0f1628]", dotColor)} />
      <div className="min-w-0 flex-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)]/80 p-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-[var(--text-muted)]">{event.time}</span>
          <span className="text-xs font-semibold text-[var(--text-secondary)]">{event.label}</span>
          {event.side !== "—" ? (
            <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold", event.side === "CALL" ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400")}>
              {event.side}
            </span>
          ) : null}
          {event.price != null ? <span className="font-mono text-xs text-teal-300">@ {fmtPx(event.price)}</span> : null}
        </div>
        <p className="mt-1 whitespace-pre-line text-[11px] text-[var(--text-muted)]">{event.detail}</p>
      </div>
    </div>
  );
}

/* ─── Planned Levels ─── */

export function PlannedLevelsSection({ levels, date }: { levels: PlannedLevel[]; date: string }) {
  return (
    <BtCard>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Planned Strategy Levels</h3>
        <p className="text-xs text-[var(--text-muted)]">{fmtDate(date)} — index levels per strategy rules</p>
      </div>
      <div className="overflow-auto rounded-lg border border-[var(--border-subtle)]">
        <table className="w-full min-w-[720px] text-left text-[11px]">
          <thead className="sticky top-0 bg-[var(--surface-elevated)] text-[var(--text-muted)]">
            <tr>
              {["Type", "Side", "Level", "Lots", "TP1", "TP2 Trail", "Stop Loss", "Note"].map((h) => (
                <th key={h} className="px-2 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {levels.map((l, i) => (
              <tr key={i} className="border-t border-white/[0.04] hover:bg-white/[0.02]">
                <td className="px-2 py-1.5 font-medium text-[var(--text-secondary)]">{levelTypeLabel(l.type)}</td>
                <td className={cn("px-2 py-1.5 font-semibold", l.side === "CALL" ? "text-emerald-400" : l.side === "PUT" ? "text-rose-400" : "text-[var(--text-muted)]")}>{l.side}</td>
                <td className="px-2 py-1.5 font-mono text-amber-300">{l.level > 0 ? fmtPx(l.level) : l.note}</td>
                <td className="px-2 py-1.5">{l.lots || "—"}</td>
                <td className="px-2 py-1.5 font-mono">{l.tp1 != null ? fmtPx(l.tp1) : "—"}</td>
                <td className="px-2 py-1.5 font-mono">{l.tp2Trail != null ? l.tp2Trail : "—"}</td>
                <td className="px-2 py-1.5 font-mono text-rose-400/90">{l.stopLoss != null ? fmtPx(l.stopLoss) : "—"}</td>
                <td className="px-2 py-1.5 text-[var(--text-muted)]">{l.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </BtCard>
  );
}

/* ─── Interactive Price Chart ─── */

type ChartLevels = { base: number; callTrigger: number; putTrigger: number };

export function PriceChartSection({
  candles,
  levels,
  timeline,
  date,
}: {
  candles: ChartCandle[];
  levels: ChartLevels;
  timeline: TimelineEvent[];
  date: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState(0);
  const [drag, setDrag] = useState<{ x: number; off: number } | null>(null);
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(null);

  const markers = useMemo(
    () => timeline.filter((t) => t.price != null && t.event !== "BASE_CAPTURED"),
    [timeline],
  );

  const draw = useCallback(() => {
    if (!candles.length) return;
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || !candles.length) return;

    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth;
    const h = 380;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#0a0f1a";
    ctx.fillRect(0, 0, w, h);

    const pad = { l: 56, r: 12, t: 16, b: 28 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;

    const visCount = Math.max(20, Math.floor(candles.length / zoom));
    const maxOff = Math.max(0, candles.length - visCount);
    const off = Math.min(maxOff, Math.max(0, offset));
    const slice = candles.slice(off, off + visCount);

    let yMin = Infinity;
    let yMax = -Infinity;
    for (const c of slice) {
      yMin = Math.min(yMin, c.low, levels.putTrigger, levels.base - 50);
      yMax = Math.max(yMax, c.high, levels.callTrigger, levels.base + 50);
      if (c.adaptiveHigh != null) yMax = Math.max(yMax, c.adaptiveHigh);
      if (c.adaptiveLow != null) yMin = Math.min(yMin, c.adaptiveLow);
    }
    const yPad = (yMax - yMin) * 0.08 || 50;
    yMin -= yPad;
    yMax += yPad;

    const yScale = (p: number) => pad.t + plotH - ((p - yMin) / (yMax - yMin)) * plotH;
    const xScale = (i: number) => pad.l + (i / Math.max(slice.length - 1, 1)) * plotW;

    const drawHLine = (price: number, color: string, label: string, dash = false) => {
      const y = yScale(price);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      if (dash) ctx.setLineDash([4, 4]);
      else ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + plotW, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "10px monospace";
      ctx.fillText(`${label} ${price.toFixed(0)}`, pad.l + 4, y - 3);
    };

    drawHLine(levels.base, "#fbbf24", "BASE");
    drawHLine(levels.callTrigger, "#34d399", "CALL+");
    drawHLine(levels.putTrigger, "#f87171", "PUT−");

    const cw = Math.max(2, plotW / slice.length - 1);
    slice.forEach((c, i) => {
      const x = xScale(i);
      const up = c.close >= c.open;
      const col = up ? "#34d399" : "#f87171";
      const yO = yScale(c.open);
      const yC = yScale(c.close);
      const yH = yScale(c.high);
      const yL = yScale(c.low);
      ctx.strokeStyle = col;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(x, yH);
      ctx.lineTo(x, yL);
      ctx.stroke();
      const top = Math.min(yO, yC);
      const bot = Math.max(yO, yC);
      ctx.fillRect(x - cw / 2, top, cw, Math.max(1, bot - top));
    });

    const drawSeries = (key: "adaptiveHigh" | "adaptiveLow", color: string) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      let started = false;
      slice.forEach((c, i) => {
        const val = c[key];
        if (val == null) return;
        const x = xScale(i);
        const y = yScale(val);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      if (started) ctx.stroke();
      ctx.setLineDash([]);
    };
    drawSeries("adaptiveHigh", "#a78bfa");
    drawSeries("adaptiveLow", "#38bdf8");

    for (const m of markers) {
      const idx = slice.findIndex((c) => c.time === m.time);
      if (idx < 0 || m.price == null) continue;
      const x = xScale(idx);
      const y = yScale(m.price);
      ctx.fillStyle = m.side === "CALL" ? "#2dd4bf" : m.side === "PUT" ? "#fb7185" : "#94a3b8";
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    }

    if (hover && hover.idx >= 0 && hover.idx < slice.length) {
      const c = slice[hover.idx];
      const x = xScale(hover.idx);
      ctx.strokeStyle = "rgba(148,163,184,0.4)";
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + plotH);
      ctx.stroke();
      const tip = `${c.time}  O:${c.open.toFixed(0)} H:${c.high.toFixed(0)} L:${c.low.toFixed(0)} C:${c.close.toFixed(0)}`;
      ctx.fillStyle = "rgba(15,22,40,0.95)";
      ctx.fillRect(Math.min(x + 8, w - 180), pad.t + 4, 172, 18);
      ctx.fillStyle = "#e2e8f0";
      ctx.font = "10px monospace";
      ctx.fillText(tip, Math.min(x + 12, w - 176), pad.t + 16);
    }

    ctx.fillStyle = "#64748b";
    ctx.font = "10px sans-serif";
    for (let i = 0; i < 5; i++) {
      const p = yMin + ((yMax - yMin) * i) / 4;
      const y = yScale(p);
      ctx.fillText(p.toFixed(0), 4, y + 3);
    }
  }, [candles, levels, markers, zoom, offset, hover]);

  useEffect(() => {
    draw();
    const ro = new ResizeObserver(draw);
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [draw]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(8, Math.max(0.5, z + (e.deltaY > 0 ? -0.15 : 0.15))));
  };

  const onMouseDown = (e: React.MouseEvent) => setDrag({ x: e.clientX, off: offset });
  const onMouseMove = (e: React.MouseEvent) => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas || !candles.length) return;
    const rect = canvas.getBoundingClientRect();
    const pad = { l: 56, r: 12 };
    const plotW = rect.width - pad.l - pad.r;
    const visCount = Math.max(20, Math.floor(candles.length / zoom));
    const slice = candles.slice(offset, offset + visCount);
    const relX = e.clientX - rect.left - pad.l;
    const idx = Math.round((relX / plotW) * (slice.length - 1));
    if (idx >= 0 && idx < slice.length) setHover({ idx, x: e.clientX, y: e.clientY });

    if (drag) {
      const dx = e.clientX - drag.x;
      const barsMoved = Math.round(-dx / (plotW / visCount));
      setOffset(Math.max(0, drag.off + barsMoved));
    }
  };
  const onMouseUp = () => setDrag(null);
  const onMouseLeave = () => {
    setDrag(null);
    setHover(null);
  };

  if (!candles.length) {
    return (
      <BtCard>
        <div className="mb-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Price Chart</h3>
          <p className="text-xs text-[var(--text-muted)]">{fmtDate(date)} — restart backend worker after update for candle chart</p>
        </div>
        <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-[var(--border-subtle)] bg-[var(--surface-elevated)] text-xs text-[var(--text-muted)]">
          Base {fmtPx(levels.base)} · Call {fmtPx(levels.callTrigger)} · Put {fmtPx(levels.putTrigger)}
        </div>
      </BtCard>
    );
  }

  return (
    <BtCard className="!p-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] p-4">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Price Chart</h3>
          <p className="text-xs text-[var(--text-muted)]">{fmtDate(date)} · 1m candles with base, triggers & trade markers</p>
        </div>
        <div className="flex gap-1">
          <ChartBtn onClick={() => setZoom((z) => Math.min(8, z + 0.25))} title="Zoom in"><Plus className="h-3.5 w-3.5" /></ChartBtn>
          <ChartBtn onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} title="Zoom out"><Minus className="h-3.5 w-3.5" /></ChartBtn>
          <ChartBtn onClick={() => { setZoom(1); setOffset(0); }} title="Reset"><RotateCcw className="h-3.5 w-3.5" /></ChartBtn>
          <ChartBtn onClick={() => setOffset(0)} title="Go to start"><ChevronLeft className="h-3.5 w-3.5" /></ChartBtn>
          <ChartBtn onClick={() => setOffset(Math.max(0, candles.length - Math.floor(candles.length / zoom)))} title="Go to end"><ChevronRight className="h-3.5 w-3.5" /></ChartBtn>
        </div>
      </div>
      <div
        ref={wrapRef}
        className="cursor-crosshair select-none"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
      >
        <canvas ref={canvasRef} />
      </div>
      <div className="flex flex-wrap gap-4 border-t border-[var(--border-subtle)] px-4 py-2 text-[10px] text-[var(--text-muted)]">
        <span><span className="inline-block h-2 w-2 rounded-full bg-amber-400" /> Base</span>
        <span><span className="inline-block h-2 w-2 rounded-full bg-emerald-400" /> Call trigger</span>
        <span><span className="inline-block h-2 w-2 rounded-full bg-rose-400" /> Put trigger</span>
        <span><span className="inline-block h-0.5 w-3 bg-violet-400" /> Adaptive High</span>
        <span><span className="inline-block h-0.5 w-3 bg-sky-400" /> Adaptive Low</span>
        <span>Triggers on intrabar touch (not close-only) · Scroll zoom · Drag pan</span>
      </div>
    </BtCard>
  );
}

function ChartBtn({ children, onClick, title }: { children: React.ReactNode; onClick: () => void; title: string }) {
  return (
    <button type="button" title={title} onClick={onClick} className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] text-[var(--text-muted)] transition hover:border-teal-500/40 hover:text-teal-400">
      {children}
    </button>
  );
}

/* ─── Net Point Breakdown ─── */

export function NetPointBreakdown({ data }: { data: NetBreakdown }) {
  return (
    <BtCard>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Net Points Breakdown</h3>
        <p className="text-xs text-[var(--text-muted)]">Analysis by day, side, exit reason & entry type</p>
      </div>
      <div className="mb-4 rounded-xl border border-white/[0.08] bg-gradient-to-r from-[#0c1220] to-[#111827] p-4 text-center">
        <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Total Net Points</p>
        <p className={cn("font-mono text-3xl font-bold", data.total >= 0 ? "text-emerald-400" : "text-rose-400")}>{data.total}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <BreakdownCard title="By Day" rows={data.byDay.map((d) => ({ label: fmtDate(d.date), value: d.points }))} />
        <BreakdownCard title="By Side" rows={Object.entries(data.bySide).map(([k, v]) => ({ label: k, value: v }))} />
        <BreakdownCard title="By Exit Reason" rows={Object.entries(data.byReason).map(([k, v]) => ({ label: k.replaceAll("_", " "), value: v }))} />
        <BreakdownCard title="By Entry Type" rows={Object.entries(data.byEntryType).map(([k, v]) => ({ label: k.replaceAll("_", " "), value: v }))} />
      </div>
    </BtCard>
  );
}

function BreakdownCard({ title, rows }: { title: string; rows: { label: string; value: number }[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] p-3">
      <p className="mb-2 text-xs font-semibold text-[var(--text-muted)]">{title}</p>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex justify-between text-[11px]">
              <span className="text-[var(--text-muted)]">{r.label}</span>
              <span className={cn("font-mono font-semibold", r.value >= 0 ? "text-emerald-400" : "text-rose-400")}>{r.value}</span>
            </div>
            <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-slate-800">
              <div
                className={cn("h-full rounded-full", r.value >= 0 ? "bg-emerald-500/70" : "bg-rose-500/70")}
                style={{ width: `${(Math.abs(r.value) / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
        {!rows.length ? <p className="text-[11px] text-slate-600">—</p> : null}
      </div>
    </div>
  );
}

/* ─── Trade Record (table) ─── */

export function TradeRecordSection({
  cycleRecords,
  onExportExcel,
  onExportCsv,
}: {
  cycleRecords: CycleTradeRecord[];
  onExportExcel: () => void;
  onExportCsv?: () => void;
}) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return cycleRecords;
    const q = search.toLowerCase();
    return cycleRecords.filter((r) =>
      [
        r.date,
        r.side,
        r.cycleId,
        r.cycleKind,
        r.initialEntry?.strike,
        r.reentryStrike,
        r.exitReason,
        r.initialEntry?.time,
        r.tp1Time,
        r.tp2Time,
      ].some((x) => String(x ?? "").toLowerCase().includes(q)),
    );
  }, [cycleRecords, search]);

  function formatLegSummary(record: CycleTradeRecord) {
    const entry = record.initialEntry;
    const entryText = entry
      ? `${entry.time} @ ${fmtPx(entry.indexPrice)} · ${entry.strike} · ${entry.lots} lot`
      : "—";
    if (!record.averaging.length) return entryText;
    const avgText = record.averaging
      .map((leg, index) => `AVG${index + 1} ${leg.time} @ ${fmtPx(leg.indexPrice)} · ${leg.strike} · ${leg.lots} lot`)
      .join(" | ");
    return `${entryText}\n${avgText}`;
  }

  function formatTp1Summary(record: CycleTradeRecord) {
    if (record.firstEntryTp1) {
      return `First TP1: ${record.firstEntryTp1.time} @ ${fmtPx(record.firstEntryTp1.price)} · ${record.firstEntryTp1.lots} lot · +${record.firstEntryTp1.pnl} pts`;
    }
    if (record.tp1Price != null) {
      return `TP1: ${record.tp1Time ?? "—"} @ ${fmtPx(record.tp1Price)} · ${record.tp1ExitLots} lot exit`;
    }
    return "—";
  }

  function formatFinalExitSummary(record: CycleTradeRecord) {
    if (record.tp2ExitPrice == null) return "—";
    const adaptiveLevel =
      record.tp2AdaptiveHigh != null
        ? `Adaptive High ${fmtPx(record.tp2AdaptiveHigh)}`
        : record.tp2AdaptiveLow != null
          ? `Adaptive Low ${fmtPx(record.tp2AdaptiveLow)}`
          : null;
    const pnlText = record.tp2Pnl != null ? `+${record.tp2Pnl} pts` : null;
    return [
      `${record.tp2Time ?? "—"} @ ${fmtPx(record.tp2ExitPrice)}`,
      record.exitReason || null,
      adaptiveLevel,
      pnlText,
    ]
      .filter(Boolean)
      .join("\n");
  }

  return (
    <BtCard className="!p-0 overflow-hidden">
      <div className="border-b border-[var(--border-subtle)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">Trade Record</h3>
            <p className="text-xs text-[var(--text-muted)]">
              {filtered.length} trade cycle(s) · one row per full trade
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {onExportCsv ? (
              <button type="button" onClick={onExportCsv} className="bt-btn-secondary text-[11px]">
                <Download className="h-3 w-3" /> CSV
              </button>
            ) : null}
            <button type="button" onClick={onExportExcel} className="bt-btn-secondary text-[11px]">
              <Download className="h-3 w-3" /> Excel
            </button>
          </div>
        </div>
        <div className="relative mt-3">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className="h-9 w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] pl-8 pr-3 text-xs text-[var(--text-secondary)] outline-none focus:border-teal-500/50"
            placeholder="Search date, side, cycle, strike, exit reason…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <div className="max-h-[600px] overflow-auto">
        <table className="w-full min-w-[1700px] text-left text-[11px]">
          <thead className="sticky top-0 z-10 bg-[var(--surface-elevated)] text-[var(--text-muted)]">
            <tr>
              {[
                "#",
                "Date",
                "Cycle",
                "Side",
                "Type",
                "Base",
                "Trigger",
                "Entry Flow",
                "First Entry TP1",
                "Avg TP1",
                "Final Exit",
                "SL",
                "Total Lots",
                "Exit Reason",
                "Cycle P&L",
                "Running",
              ].map((label) => (
                <th key={label} className="whitespace-nowrap px-2 py-2 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((record, idx) => {
              const entryTone = record.side === "CALL" ? "text-emerald-400" : "text-rose-400";
              const pnlTone = record.cyclePnl >= 0 ? "text-emerald-400" : "text-rose-400";
              return (
                <tr key={record.uid} className="border-t border-white/[0.04] align-top hover:bg-white/[0.02]">
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">{idx + 1}</td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">{fmtDate(record.date)}</td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">{record.cycleId}</td>
                  <td className={cn("whitespace-nowrap px-2 py-2 font-mono font-semibold", entryTone)}>{record.side}</td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-teal-300">
                    {record.cycleKind === "INITIAL" ? "Initial Trade" : "Re-entry Trade"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">
                    {record.basePrice != null ? fmtPx(record.basePrice) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">
                    {record.triggerPrice != null ? fmtPx(record.triggerPrice) : "—"}
                  </td>
                  <td className="px-2 py-2 font-mono whitespace-pre-line text-[var(--text-secondary)]">
                    {formatLegSummary(record)}
                  </td>
                  <td className="px-2 py-2 font-mono whitespace-pre-line text-sky-300">
                    {formatTp1Summary(record)}
                  </td>
                  <td className="px-2 py-2 font-mono whitespace-pre-line text-violet-300">
                    {record.avgTp1Exits.length
                      ? record.avgTp1Exits
                          .map((avg) => `${avg.time} @ ${fmtPx(avg.price)} · ${avg.lots} lot · +${avg.pnl} pts`)
                          .join("\n")
                      : "—"}
                  </td>
                  <td className="px-2 py-2 font-mono whitespace-pre-line text-[var(--text-secondary)]">
                    {formatFinalExitSummary(record)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">
                    {record.stopLoss != null ? fmtPx(record.stopLoss) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">
                    {record.totalLotsUsed || "—"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">
                    {record.exitReason || "—"}
                  </td>
                  <td className={cn("whitespace-nowrap px-2 py-2 font-mono font-semibold", pnlTone)}>
                    {record.cyclePnl}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-[var(--text-secondary)]">
                    {record.runningPnl}
                  </td>
                </tr>
              );
            })}
            {!filtered.length ? (
              <tr>
                <td colSpan={15} className="px-3 py-8 text-center text-[var(--text-muted)]">
                  No trade records match your search.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </BtCard>
  );
}

/* ─── Backtest guide ─── */

export function BacktestGuideSection() {
  const [open, setOpen] = useState(false);
  return (
    <BtCard className="!p-0 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left transition hover:bg-white/[0.02]"
      >
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Backtest samajhna — kaise kaam karta hai?</h3>
          <p className="text-xs text-[var(--text-muted)]">Live strategy jaisi logic · historical candles par simulate</p>
        </div>
        <span className="text-xs text-teal-400">{open ? "Hide" : "Show"}</span>
      </button>
      {open ? (
        <div className="space-y-4 border-t border-[var(--border-subtle)] px-4 py-4 text-xs leading-relaxed text-[var(--text-muted)]">
          <div>
            <p className="mb-1 font-semibold text-[var(--text-secondary)]">1. Settings (alag live se)</p>
            <p>Backtest ke settings yahan local hain — aap alag parameters test kar sakte ho bina live settings change kiye. <strong className="text-[var(--text-secondary)]">Load Live Settings</strong> se ek baar copy ho sakta hai.</p>
          </div>
          <div>
            <p className="mb-1 font-semibold text-[var(--text-secondary)]">2. Har din kya hota hai</p>
            <ul className="list-inside list-disc space-y-1">
              <li><strong className="text-amber-400/90">Base</strong> — 09:15 ki 1-min candle close</li>
              <li><strong className="text-emerald-400/90">Call trigger</strong> = Base + Entry Gap · <strong className="text-rose-400/90">Put trigger</strong> = Base − Entry Gap</li>
              <li>Index <strong className="text-[var(--text-secondary)]">cross</strong> par entry (intrabar touch — close-only nahi)</li>
              <li><strong className="text-[var(--text-secondary)]">Sirf 1 Initial Entry per day</strong> — baad mein sirf Re-entry</li>
              <li>Re-entry SL = Adaptive High − Stop (CALL) / Adaptive Low + Stop (PUT)</li>
              <li><strong className="text-[var(--text-secondary)]">Averaging</strong> — price ulta move kare to gap par extra lots (max entries tak)</li>
              <li><strong className="text-[var(--text-secondary)]">TP1</strong> — first entry (2 lots) @ <strong className="text-[var(--text-secondary)]">+70pt</strong> · averaging lots @ <strong className="text-[var(--text-secondary)]">+45pt</strong> · core 1 lot <strong className="text-[var(--text-secondary)]">TP2 trail</strong></li>
              <li><strong className="text-[var(--text-secondary)]">Stop</strong> — first entry −191 · TP1 ke baad SL +70 · re-entry par adaptive high −191 (trail)</li>
            </ul>
          </div>
          <div>
            <p className="mb-1 font-semibold text-[var(--text-secondary)]">3. Results sections</p>
            <ul className="list-inside list-disc space-y-1">
              <li><strong className="text-[var(--text-secondary)]">Base & Trigger</strong> — date-wise levels</li>
              <li><strong className="text-[var(--text-secondary)]">Timeline</strong> — kab entry/exit hua</li>
              <li><strong className="text-[var(--text-secondary)]">Chart</strong> — us din ki price + levels (zoom/pan)</li>
              <li><strong className="text-[var(--text-secondary)]">Net breakdown</strong> — points ka hisaab</li>
              <li><strong className="text-[var(--text-secondary)]">Trade Record</strong> — har cycle ek card (Initial/Re-entry, AVG, TP1, TP2, Net P&L)</li>
              <li><strong className="text-[var(--text-secondary)]">Timeline</strong> — din bhar events ka flow</li>
            </ul>
          </div>
          <div>
            <p className="mb-1 font-semibold text-[var(--text-secondary)]">4. P&L ka matlab</p>
            <p>Points = index move × lots (CALL: exit − entry, PUT: entry − exit). Yeh wahi engine hai jo live paper/real trading use karti hai — sirf historical candles se chalaya jata hai.</p>
          </div>
        </div>
      ) : null}
    </BtCard>
  );
}
