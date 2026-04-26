import { Loader2, CheckCircle, XCircle } from "lucide-react";
import type { WikiEventType } from "../../hooks/wikiTypes";

interface WikiGenerationProgressProps {
  status: WikiEventType | null;
}

export default function WikiGenerationProgress({ status }: WikiGenerationProgressProps) {
  if (!status) return null;

  const isRunning = status === "wiki:generation_started";
  const isDone = status === "wiki:generation_completed";
  const isFailed = status === "wiki:generation_failed";

  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm ${
        isFailed
          ? "border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300"
          : isDone
            ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
            : "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300"
      }`}
    >
      {isRunning && <Loader2 size={16} className="animate-spin" />}
      {isDone && <CheckCircle size={16} />}
      {isFailed && <XCircle size={16} />}
      <span>
        {isRunning && "Wiki generation in progress..."}
        {isDone && "Wiki generation completed"}
        {isFailed && "Wiki generation failed"}
      </span>
    </div>
  );
}
