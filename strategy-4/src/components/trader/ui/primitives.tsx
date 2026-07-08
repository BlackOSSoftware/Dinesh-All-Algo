"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { cn } from "@/components/ui";

export function PageHeader({
  title,
  subtitle,
  action,
  compact,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <h1
          className={cn(
            "font-semibold tracking-tight text-[var(--text-primary)]",
            compact ? "text-lg" : "text-2xl sm:text-3xl",
          )}
        >
          {title}
        </h1>
        {subtitle ? (
          <p className={cn("text-[var(--text-secondary)]", compact ? "text-xs" : "mt-1.5 text-sm")}>{subtitle}</p>
        ) : null}
      </div>
      {action}
    </motion.div>
  );
}

export function PremiumCard({
  children,
  className,
  hover = false,
  delay = 0,
  compact = false,
}: {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  delay?: number;
  compact?: boolean;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay }}
      whileHover={hover ? { y: -2, transition: { duration: 0.2 } } : undefined}
      className={cn(
        "rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] shadow-[var(--shadow-card)]",
        compact ? "p-3" : "rounded-[var(--radius-card)] p-5 sm:p-6",
        hover && "transition-shadow hover:shadow-[var(--shadow-card-hover)]",
        className,
      )}
    >
      {children}
    </motion.section>
  );
}

export function CardTitle({
  title,
  subtitle,
  action,
  compact,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-2", compact ? "mb-2" : "mb-5")}>
      <div>
        <h2 className={cn("font-semibold text-[var(--text-primary)]", compact ? "text-xs" : "text-sm tracking-wide")}>
          {title}
        </h2>
        {subtitle ? <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function MetricBadge({
  label,
  value,
  tone = "neutral",
  size = "md",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "neutral" | "success" | "danger" | "warning" | "info";
  size?: "md" | "lg";
}) {
  const tones = {
    neutral: "border-[var(--border-subtle)] bg-[var(--surface-muted)] text-[var(--text-primary)]",
    success: "border-emerald-500/20 bg-[var(--success-soft)] text-emerald-600 dark:text-emerald-400",
    danger: "border-rose-500/20 bg-[var(--danger-soft)] text-rose-600 dark:text-rose-400",
    warning: "border-amber-500/20 bg-[var(--warning-soft)] text-amber-700 dark:text-amber-400",
    info: "border-cyan-500/20 bg-cyan-500/10 text-cyan-700 dark:text-cyan-400",
  };

  return (
    <div
      className={cn(
        "inline-flex flex-col rounded-xl border px-4 py-2.5",
        tones[tone],
        size === "lg" && "min-w-[140px] px-5 py-3",
      )}
    >
      <span className="text-[10px] font-bold uppercase tracking-[0.14em] opacity-80">{label}</span>
      <span
        className={cn(
          "mt-1 font-semibold tracking-tight",
          size === "lg" ? "text-xl sm:text-2xl" : "text-base",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function SummaryStatCard({
  icon,
  label,
  value,
  sub,
  tone = "neutral",
  delay = 0,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "neutral" | "success" | "danger" | "warning" | "info";
  delay?: number;
}) {
  const ring =
    tone === "success"
      ? "from-emerald-500/10 to-transparent"
      : tone === "danger"
        ? "from-rose-500/10 to-transparent"
        : tone === "warning"
          ? "from-amber-500/10 to-transparent"
          : tone === "info"
            ? "from-cyan-500/10 to-transparent"
            : "from-slate-500/5 to-transparent";

  return (
    <PremiumCard delay={delay} hover className="relative overflow-hidden">
      <div className={cn("pointer-events-none absolute inset-0 bg-gradient-to-br", ring)} />
      <div className="relative flex items-start justify-between gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-muted)] text-[var(--text-secondary)]">
          {icon}
        </div>
      </div>
      <p className="relative mt-4 text-[11px] font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]">
        {label}
      </p>
      <div className="relative mt-2 text-2xl font-semibold tracking-tight text-[var(--text-primary)] sm:text-3xl">
        {value}
      </div>
      {sub ? <div className="relative mt-2 text-sm text-[var(--text-secondary)]">{sub}</div> : null}
    </PremiumCard>
  );
}

export function FloatingField({
  id,
  label,
  help,
  value,
  onChange,
  type = "text",
  placeholder,
  min,
  max,
  step,
}: {
  id: string;
  label: string;
  help?: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: string | number;
}) {
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (!focused) setDraft(value);
  }, [value, focused]);

  const display = focused ? draft : value;
  const filled = display.length > 0;
  return (
    <div className="relative">
      <input
        id={id}
        type={type}
        value={display}
        placeholder={placeholder ?? " "}
        min={min}
        max={max}
        step={step}
        onFocus={() => {
          setFocused(true);
          setDraft(value);
        }}
        onChange={(e) => {
          setDraft(e.target.value);
          onChange(e.target.value);
        }}
        onBlur={() => {
          setFocused(false);
          onChange(draft);
        }}
        className={cn(
          "peer w-full rounded-[var(--radius-input)] border border-[var(--border-subtle)] bg-[var(--surface-muted)] px-4 pb-3 pt-6 text-sm font-medium text-[var(--text-primary)] outline-none transition",
          "placeholder:text-transparent focus:border-[var(--accent)] focus:bg-[var(--surface-elevated)] focus:ring-4 focus:ring-[var(--accent-soft)]",
        )}
      />
      <label
        htmlFor={id}
        className={cn(
          "pointer-events-none absolute left-4 text-[var(--text-muted)] transition-all",
          filled
            ? "top-2 text-[10px] font-bold uppercase tracking-wider text-[var(--accent)]"
            : "top-1/2 -translate-y-1/2 text-sm peer-focus:top-2 peer-focus:translate-y-0 peer-focus:text-[10px] peer-focus:font-bold peer-focus:uppercase peer-focus:tracking-wider peer-focus:text-[var(--accent)]",
        )}
      >
        <span className="pointer-events-auto inline-flex items-center">
          {label}
          {help ? <InfoTip text={help} /> : null}
        </span>
      </label>
    </div>
  );
}

export function StatusPillLarge({
  label,
  active,
  activeClass,
  inactiveClass,
}: {
  label: string;
  active: boolean;
  activeClass: string;
  inactiveClass: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-4 py-2 text-sm font-bold tracking-wide",
        active ? activeClass : inactiveClass,
      )}
    >
      {label}
    </span>
  );
}

export function DataValue({
  value,
  className,
  large,
}: {
  value: React.ReactNode;
  className?: string;
  large?: boolean;
}) {
  const empty = value === null || value === undefined || value === "" || value === "—";
  return (
    <span
      className={cn(
        "font-mono tabular-nums tracking-tight",
        large ? "text-xl font-semibold sm:text-2xl" : "text-sm font-semibold",
        empty ? "text-[var(--text-muted)]" : "text-[var(--text-primary)]",
        className,
      )}
    >
      {empty ? "—" : value}
    </span>
  );
}

export function InfoTip({ text }: { text: string }) {
  return (
    <span className="group relative ml-1 inline-flex align-middle">
      <button type="button" aria-label="Help" className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-[var(--border-subtle)] text-[10px] font-bold text-[var(--text-muted)] hover:border-[var(--accent)] hover:text-[var(--accent)]">i</button>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-56 -translate-x-1/2 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-3 py-2 text-[11px] font-normal leading-snug text-[var(--text-secondary)] shadow-lg group-hover:block group-focus-within:block">{text}</span>
    </span>
  );
}

export function FieldLabel({ label, help }: { label: string; help?: string }) {
  return (
    <span className="inline-flex items-center text-sm font-medium text-[var(--text-secondary)]">
      {label}
      {help ? <InfoTip text={help} /> : null}
    </span>
  );
}
