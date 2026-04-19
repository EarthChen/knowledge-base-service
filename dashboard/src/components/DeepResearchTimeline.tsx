import { CheckCircle2, Circle, Loader2, AlertCircle } from "lucide-react";

export type StageEvent = {
  type: "plan" | "progress" | "search_done" | "synthesis" | "conclusion" | "error";
  data: Record<string, unknown>;
  status: "done" | "active" | "pending";
};

function StatusIcon({ status }: { status: StageEvent["status"] }) {
  if (status === "done") return <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-green-500" />;
  if (status === "active") return <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin text-amber-500" />;
  return <Circle size={16} className="mt-0.5 shrink-0 text-gray-300 dark:text-gray-600" />;
}

function stageLabel(s: StageEvent, isZh: boolean): string {
  switch (s.type) {
    case "plan":
      return isZh ? "搜索规划" : "Search Plan";
    case "progress": {
      const iter = (s.data.iteration as number) ?? 0;
      return isZh ? `第 ${iter + 1} 轮检索` : `Search Round ${iter + 1}`;
    }
    case "search_done": {
      const iter = (s.data.iteration as number) ?? 0;
      const count = (s.data.result_count as number) ?? 0;
      return isZh
        ? `第 ${iter + 1} 轮完成 — ${count} 个结果`
        : `Round ${iter + 1} Done — ${count} results`;
    }
    case "synthesis": {
      const iter = (s.data.iteration as number) ?? 0;
      const sufficient = s.data.sufficient as boolean;
      return isZh
        ? `第 ${iter + 1} 轮分析 — ${sufficient ? "信息充分" : "继续研究..."}`
        : `Round ${iter + 1} Analysis — ${sufficient ? "Sufficient" : "Continuing..."}`;
    }
    case "conclusion":
      return isZh ? "综合结论" : "Final Conclusion";
    case "error":
      return isZh
        ? `错误: ${(s.data.message as string) || "未知"}`
        : `Error: ${(s.data.message as string) || "Unknown"}`;
    default:
      return s.type;
  }
}

type Props = {
  stages: StageEvent[];
  isZh?: boolean;
};

export default function DeepResearchTimeline({ stages, isZh = false }: Props) {
  if (stages.length === 0) return null;

  return (
    <ol className="space-y-2">
      {stages.map((s, i) => (
        <li
          key={`${s.type}-${i}`}
          className={`flex items-start gap-3 rounded-lg border px-4 py-2.5 text-sm transition-colors ${
            s.type === "error"
              ? "border-red-200 bg-red-50/60 dark:border-red-900/50 dark:bg-red-950/40"
              : s.status === "done"
                ? "border-green-100 bg-green-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/30"
                : s.status === "active"
                  ? "border-amber-200 bg-amber-50/40 dark:border-amber-900/50 dark:bg-amber-950/30"
                  : "border-gray-100 bg-gray-50/40 opacity-50 dark:border-gray-700 dark:bg-gray-800/40"
          }`}
        >
          {s.type === "error" ? (
            <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
          ) : (
            <StatusIcon status={s.status} />
          )}
          <span
            className={
              s.status === "active"
                ? "font-medium text-amber-800 dark:text-amber-200"
                : "text-gray-700 dark:text-gray-300"
            }
          >
            {stageLabel(s, isZh)}
          </span>
        </li>
      ))}
    </ol>
  );
}
