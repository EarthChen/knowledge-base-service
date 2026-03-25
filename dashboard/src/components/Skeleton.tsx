export function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-slate-800 bg-slate-850 p-5">
      <div className="h-3 w-20 rounded bg-slate-700/60" />
      <div className="mt-3 h-7 w-16 rounded bg-slate-700/60" />
    </div>
  );
}

export function SkeletonLine({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-slate-700/60 ${className}`} />
  );
}
