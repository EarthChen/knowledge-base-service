import type { UseMutationResult } from "@tanstack/react-query";
import type { BlastRadiusResponse } from "../../api/types";
import type { ApiError } from "../../api/client";
import { useI18n } from "../../i18n/context";
import { depthRowClass, INPUT_CLASS } from "./graphLayout";

type BlastRadiusPanelProps = {
  blastNamesInput: string;
  setBlastNamesInput: (v: string) => void;
  blastDepth: number;
  setBlastDepth: (v: number) => void;
  blastRepo: string;
  setBlastRepo: (v: string) => void;
  blastMutation: UseMutationResult<
    BlastRadiusResponse,
    ApiError,
    { entity_names: string[]; max_depth: number; repository?: string | null },
    unknown
  >;
  onRun: () => void;
};

export default function BlastRadiusPanel({
  blastNamesInput,
  setBlastNamesInput,
  blastDepth,
  setBlastDepth,
  blastRepo,
  setBlastRepo,
  blastMutation,
  onRun,
}: BlastRadiusPanelProps) {
  const { t } = useI18n();

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {t.explorer.blastTitle}
      </h3>
      <label className="mt-3 block">
        <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
          {t.explorer.blastNamesLabel}
        </span>
        <textarea
          value={blastNamesInput}
          onChange={(e) => setBlastNamesInput(e.target.value)}
          rows={2}
          placeholder={t.explorer.blastNamesPlaceholder}
          className={`w-full resize-y ${INPUT_CLASS}`}
        />
      </label>
      <div className="mt-2 flex flex-wrap gap-2">
        <label className="flex-1 min-w-[100px]">
          <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
            {t.explorer.blastMaxDepth}
          </span>
          <input
            type="number"
            min={1}
            max={5}
            value={blastDepth}
            onChange={(e) => setBlastDepth(Number(e.target.value) || 3)}
            className={`w-full ${INPUT_CLASS}`}
          />
        </label>
        <label className="min-w-[140px] flex-1">
          <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
            {t.explorer.blastRepositoryOptional}
          </span>
          <input
            type="text"
            value={blastRepo}
            onChange={(e) => setBlastRepo(e.target.value)}
            className={`w-full ${INPUT_CLASS}`}
          />
        </label>
      </div>
      <button
        type="button"
        onClick={onRun}
        disabled={blastMutation.isPending || !blastNamesInput.trim()}
        className="mt-3 w-full rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-500 disabled:opacity-50 dark:bg-amber-500 dark:hover:bg-amber-400"
      >
        {blastMutation.isPending ? t.explorer.blastRunning : t.explorer.blastRun}
      </button>
      {blastMutation.error ? (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{blastMutation.error.message}</p>
      ) : null}
      {blastMutation.data ? (
        <div className="mt-3 space-y-2 text-xs">
          <p className="font-medium text-gray-700 dark:text-gray-200">{t.explorer.blastAffectedTitle}</p>
          <p className="text-[11px] text-gray-600 dark:text-gray-400">
            total {blastMutation.data.total_affected} · max depth {blastMutation.data.summary.max_depth_reached}
          </p>
          <p className="text-[11px] text-gray-600 dark:text-gray-400">
            {Object.entries(blastMutation.data.summary.by_type)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
          </p>
          <p className="text-[11px] text-gray-600 dark:text-gray-400">
            {Object.entries(blastMutation.data.summary.by_relation)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
          </p>
          {(() => {
            const md = Math.max(
              blastMutation.data.summary.max_depth_reached,
              ...blastMutation.data.affected.map((l) => l.depth),
              1,
            );
            return blastMutation.data.affected.map((layer) => (
              <div key={layer.depth} className="space-y-1">
                <p
                  className={`text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 ${depthRowClass(layer.depth, md)} rounded px-2 py-0.5`}
                >
                  {t.explorer.depth} {layer.depth}
                </p>
                <ul className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-100 dark:border-gray-700">
                  {layer.nodes.map((node) => (
                    <li
                      key={node.uid}
                      className={`break-all border-b border-gray-100 px-2 py-1.5 last:border-0 dark:border-gray-800 ${depthRowClass(layer.depth, md)}`}
                    >
                      <span className="font-medium text-gray-800 dark:text-gray-100">{node.name}</span>{" "}
                      <span className="text-gray-500 dark:text-gray-400">· {node.type}</span>
                      <br />
                      <span className="text-[10px] text-gray-500 dark:text-gray-500">
                        {t.explorer.blastRelation}: {node.relation} · {t.explorer.blastConfidence}:{" "}
                        {node.confidence}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ));
          })()}
        </div>
      ) : null}
    </section>
  );
}
