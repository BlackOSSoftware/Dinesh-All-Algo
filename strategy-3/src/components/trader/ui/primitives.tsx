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
  disabled,
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
  disabled?: boolean;
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
        disabled={disabled}
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
          disabled && "cursor-not-allowed opacity-70",
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
