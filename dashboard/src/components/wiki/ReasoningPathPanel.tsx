import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReasoningPathData } from "../../hooks/wikiTypes";

interface Props {
  reasoningPath: ReasoningPathData | null | undefined;
}

const RETRIEVER_COLORS: Record<string, string> = {
  vector: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  fts: "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300",
  graph: "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
  graph_path: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  wiki_search: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300",
};

export function ReasoningPathPanel({ reasoningPath }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!reasoningPath || !reasoningPath.stages.length) return null;

  return (
    <div className="mt-3 overflow-hidden rounded-lg border">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1 bg-gray-50 px-3 py-2 text-left text-sm font-medium hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700"
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        Reasoning Path ({reasoningPath.stages.length} stages)
      </button>
      {expanded && (
        <div className="space-y-2 p-3">
          {reasoningPath.stages.map((stage, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <div className="flex shrink-0 items-center gap-1">
                <span className="w-5 text-right text-gray-400">{i + 1}.</span>
                <span
                  className={`rounded px-1.5 py-0.5 font-mono text-xs ${
                    RETRIEVER_COLORS[stage.retriever] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200"
                  }`}
                >
                  {stage.retriever}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <span className="font-medium">{stage.stage_name}</span>
                {stage.entity_hits.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {stage.entity_hits.slice(0, 8).map((e, j) => (
                      <span key={j} className="rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-gray-700">
                        {e}
                      </span>
                    ))}
                    {stage.entity_hits.length > 8 && (
                      <span className="text-xs text-gray-400">+{stage.entity_hits.length - 8}</span>
                    )}
                  </div>
                )}
              </div>
              {stage.score !== null && (
                <span className="shrink-0 text-xs text-gray-500 dark:text-gray-400">{stage.score.toFixed(2)}</span>
              )}
            </div>
          ))}
          {reasoningPath.answer_entities.length > 0 && (
            <div className="mt-2 border-t pt-2">
              <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Answer entities:</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {reasoningPath.answer_entities.map((e, i) => (
                  <span
                    key={i}
                    className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                  >
                    {e}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
