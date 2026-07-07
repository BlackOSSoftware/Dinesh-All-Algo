import type { LegEntryMode } from "@/lib/types";

export function normalizeLegEntryMode(value: unknown): LegEntryMode {
  if (typeof value !== "string") return "once";
  const s = value.trim().toLowerCase();
  if (s === "multi" || s === "repeat" || s === "multiple") return "multi";
  return "once";
}
