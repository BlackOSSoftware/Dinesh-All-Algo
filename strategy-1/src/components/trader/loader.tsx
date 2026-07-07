export function Loader({ className }: { className?: string }) {
  return (
    <span
      className={["inline-block h-4 w-4 animate-spin rounded-full border-2 border-teal-200 border-t-teal-600", className]
        .filter(Boolean)
        .join(" ")}
      aria-hidden
    />
  );
}

export function BusyOverlay({ show, label }: { show: boolean; label: string }) {
  if (!show) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 backdrop-blur-[1px]">
      <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-lg">
        <Loader />
        <span className="text-sm font-medium text-slate-700">{label}</span>
      </div>
    </div>
  );
}
