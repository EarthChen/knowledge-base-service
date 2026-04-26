const TIER_LABELS = ["Working", "Episodic", "Semantic", "Procedural"] as const;

const TIER_STYLES = [
  "bg-slate-100 text-slate-800 dark:bg-slate-800/50 dark:text-slate-200",
  "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
  "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
] as const;

export type MemoryTierIndicatorProps = { tier: 0 | 1 | 2 | 3; className?: string };

export default function MemoryTierIndicator({ tier, className }: MemoryTierIndicatorProps) {
  const label = TIER_LABELS[Math.max(0, Math.min(3, tier))] ?? "Unknown";
  const color = TIER_STYLES[Math.max(0, Math.min(3, tier))] ?? TIER_STYLES[0];
  return (
    <span
      role="img"
      aria-label={`Memory tier: ${label}`}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${color} ${className ?? ""}`.trim()}
      data-tier={tier}
    >
      {label}
    </span>
  );
}
