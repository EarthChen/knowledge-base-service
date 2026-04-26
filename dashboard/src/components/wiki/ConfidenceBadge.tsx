type Props = { score: number };

export function ConfidenceBadge({ score }: Props) {
  const tier = score >= 0.8 ? "high" : score >= 0.5 ? "medium" : "low";
  const label =
    tier === "high" ? "High Confidence" : tier === "medium" ? "Medium" : "Low Confidence";
  const color =
    tier === "high"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
      : tier === "medium"
        ? "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200"
        : "bg-rose-100 text-rose-800 dark:bg-rose-900/50 dark:text-rose-200";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${color}`}
    >
      {label} ({score.toFixed(2)})
    </span>
  );
}
