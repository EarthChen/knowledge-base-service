import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import type { CommunityInfo, CommunitiesResponse, RepositoriesResponse } from "../../api/types";
import type { ApiError } from "../../api/client";
import { useI18n } from "../../i18n/context";
import { INPUT_CLASS } from "./graphLayout";

type CommunitiesPanelProps = {
  communityRepo: string;
  setCommunityRepo: (v: string) => void;
  communityMinSize: number;
  setCommunityMinSize: (v: number) => void;
  communitiesMutation: UseMutationResult<
    CommunitiesResponse,
    ApiError,
    { repository?: string | null; min_size?: number },
    unknown
  >;
  reposQuery: UseQueryResult<RepositoriesResponse, Error>;
  selectedCommunityKey: number | null;
  onLoad: () => void;
  onCommunityClick: (c: CommunityInfo) => void;
};

export default function CommunitiesPanel({
  communityRepo,
  setCommunityRepo,
  communityMinSize,
  setCommunityMinSize,
  communitiesMutation,
  reposQuery,
  selectedCommunityKey,
  onLoad,
  onCommunityClick,
}: CommunitiesPanelProps) {
  const { t } = useI18n();

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {t.explorer.communityTitle}
      </h3>
      <label className="mt-3 block">
        <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
          {t.explorer.communityRepository}
        </span>
        <select
          value={communityRepo}
          onChange={(e) => setCommunityRepo(e.target.value)}
          className={`w-full ${INPUT_CLASS}`}
        >
          <option value="">{t.explorer.communityAllRepos}</option>
          {(reposQuery.data?.repositories ?? []).map((r) => (
            <option key={r.repository} value={r.repository}>
              {r.repository}
            </option>
          ))}
        </select>
      </label>
      <label className="mt-2 block">
        <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
          {t.explorer.communityMinSize}
        </span>
        <input
          type="number"
          min={2}
          max={50}
          value={communityMinSize}
          onChange={(e) => setCommunityMinSize(Number(e.target.value) || 3)}
          className={`w-full ${INPUT_CLASS}`}
        />
      </label>
      <button
        type="button"
        onClick={onLoad}
        disabled={communitiesMutation.isPending}
        className="mt-3 w-full rounded-lg border border-violet-300 bg-violet-50 px-3 py-2 text-sm font-medium text-violet-900 transition-colors hover:bg-violet-100 disabled:opacity-50 dark:border-violet-800 dark:bg-violet-950/60 dark:text-violet-100 dark:hover:bg-violet-900/60"
      >
        {communitiesMutation.isPending ? t.explorer.communityLoading : t.explorer.communityLoad}
      </button>
      {communitiesMutation.error ? (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{communitiesMutation.error.message}</p>
      ) : null}
      {communitiesMutation.data ? (
        <div className="mt-3 space-y-2 text-xs">
          <p className="text-gray-600 dark:text-gray-300">
            {t.explorer.communityUnclustered}: {communitiesMutation.data.unclustered_count}
          </p>
          <p className="text-[10px] text-gray-500 dark:text-gray-500">
            {t.explorer.communityClickHighlight}
          </p>
          <ul className="max-h-48 space-y-1.5 overflow-y-auto">
            {communitiesMutation.data.communities.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => onCommunityClick(c)}
                  className={`w-full rounded-lg border px-2 py-2 text-left text-xs transition-colors ${
                    selectedCommunityKey === c.id
                      ? "border-violet-500 bg-violet-50 dark:border-violet-500 dark:bg-violet-950/80"
                      : "border-gray-200 bg-gray-50 hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-800 dark:hover:bg-gray-700"
                  }`}
                >
                  <span className="font-medium text-gray-900 dark:text-gray-100">{c.label}</span>
                  <span className="ml-2 text-gray-500 dark:text-gray-400">
                    · n={c.size} · cohesion {c.cohesion}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-3 text-[11px] text-gray-500 dark:text-gray-400">{t.explorer.communityEmpty}</p>
      )}
    </section>
  );
}
