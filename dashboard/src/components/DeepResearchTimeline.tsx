import { CheckCircle2, Circle, Loader2, AlertCircle } from "lucide-react";
import { useI18n } from "../i18n/context";

export type StageEvent = {
  type:
    | "plan"
    | "progress"
    | "search_done"
    | "synthesis"
    | "conclusion"
    | "error"
    | "planning"
    | "evaluating";
  data: Record<string, unknown>;
  status: "done" | "active" | "pending";
};

function StatusIcon({ status }: { status: StageEvent["status"] }) {
  if (status === "done") return <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-green-500" />;
  if (status === "active") return <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin text-amber-500" />;
  return <Circle size={16} className="mt-0.5 shrink-0 text-gray-300 dark:text-gray-600" />;
}

function useStageLabel(s: StageEvent): string {
  const { t } = useI18n();
  switch (s.type) {
    case "plan":
      return t.search.deepResearchStagePlan;
    case "progress": {
      const iter = (s.data.iteration as number) ?? 0;
      return t.search.deepResearchRound.replace("{n}", String(iter + 1));
    }
    case "search_done": {
      const iter = (s.data.iteration as number) ?? 0;
      const count = (s.data.result_count as number) ?? 0;
      return t.search.deepResearchRoundDone
        .replace("{round}", String(iter + 1))
        .replace("{count}", String(count));
    }
    case "synthesis": {
      const iter = (s.data.iteration as number) ?? 0;
      const sufficient = s.data.sufficient as boolean;
      const suffix = sufficient ? t.search.deepResearchSufficient : t.search.deepResearchContinuing;
      return t.search.deepResearchRoundAnalysisPrefix.replace("{round}", String(iter + 1)) + suffix;
    }
    case "conclusion":
      return t.search.deepResearchConclusion;
    case "error": {
      const raw = (s.data.message as string) || t.search.deepResearchUnknown;
      return t.search.deepResearchError.replace("{message}", raw);
    }
    case "planning": {
      const round = (s.data.round as number) ?? 0;
      const subQueries = (s.data.sub_queries as string[]) ?? [];
      if (subQueries.length) {
        return t.search.ragPlanningWithQueries
          .replace("{round}", String(round))
          .replace("{queries}", subQueries.join(", "));
      }
      return t.search.ragPlanning.replace("{round}", String(round));
    }
    case "evaluating": {
      const round = (s.data.round as number) ?? 0;
      const score = (s.data.score as number) ?? 0;
      return t.search.ragEvaluating
        .replace("{round}", String(round))
        .replace("{score}", (score * 100).toFixed(0));
    }
    default:
      return s.type;
  }
}

function StageRow({ stage }: { stage: StageEvent }) {
  const text = useStageLabel(stage);
  return (
    <li
      className={`flex items-start gap-3 rounded-lg border px-4 py-2.5 text-sm transition-colors ${
        stage.type === "error"
          ? "border-red-200 bg-red-50/60 dark:border-red-900/50 dark:bg-red-950/40"
          : stage.status === "done"
            ? "border-green-100 bg-green-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/30"
            : stage.status === "active"
              ? "border-amber-200 bg-amber-50/40 dark:border-amber-900/50 dark:bg-amber-950/30"
              : "border-gray-100 bg-gray-50/40 opacity-50 dark:border-gray-700 dark:bg-gray-800/40"
      }`}
    >
      {stage.type === "error" ? (
        <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
      ) : (
        <StatusIcon status={stage.status} />
      )}
      <span
        className={
          stage.status === "active"
            ? "font-medium text-amber-800 dark:text-amber-200"
            : "text-gray-700 dark:text-gray-300"
        }
      >
        {text}
      </span>
    </li>
  );
}

type Props = {
  stages: StageEvent[];
  /** @deprecated Locale is taken from i18n context */
  isZh?: boolean;
};

export default function DeepResearchTimeline({ stages }: Props) {
  if (stages.length === 0) return null;

  return (
    <ol className="space-y-2">
      {stages.map((s, i) => (
        <StageRow key={`${s.type}-${i}`} stage={s} />
      ))}
    </ol>
  );
}
