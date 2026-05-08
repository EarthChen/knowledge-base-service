import { useState, useMemo } from "react";
import { FolderGit2, Trash2, Loader2, RefreshCw, Building2 } from "lucide-react";
import { useRepositories, useDeleteRepository } from "../api/hooks";
import { syncRepoAndWiki } from "../api/client";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { useAuth } from "../contexts/AuthContext";
import { useBusiness } from "../contexts/BusinessContext";
import { useBusinessRepositories } from "../hooks/useBusinessRepositories";
import { useToast } from "../components/Toast";
import { SkeletonLine } from "../components/Skeleton";

export default function Repositories() {
  const { data, isLoading, error, refetch } = useRepositories();
  const { currentBusiness, businesses, isLoading: businessesLoading } = useBusiness();
  const boundReposQuery = useBusinessRepositories(currentBusiness);
  const deleteMutation = useDeleteRepository();
  const { t } = useI18n();
  const { toast } = useToast();
  const { isAdmin } = useAuth();
  const [syncingRepo, setSyncingRepo] = useState<string | null>(null);

  const currentBizName =
    businesses.find((b) => b.id === currentBusiness)?.name || currentBusiness;

  const filteredRepos = useMemo(() => {
    if (!boundReposQuery.isFetched) return [];
    const all = data?.repositories ?? [];
    const bound = boundReposQuery.data?.repositories ?? [];
    const set = new Set(bound);
    if (currentBusiness === "default" && set.size === 0) {
      return all;
    }
    return all.filter((r) => set.has(r.repository));
  }, [
    data?.repositories,
    boundReposQuery.data?.repositories,
    boundReposQuery.isFetched,
    currentBusiness,
  ]);

  const tableLoading =
    isLoading || !boundReposQuery.isFetched || businessesLoading;

  async function handleDelete(repo: string) {
    const msg = t.repos.deleteConfirm.replace("{repo}", repo);
    if (!confirm(msg)) return;
    try {
      const result = await deleteMutation.mutateAsync(repo);
      toast(
        "success",
        t.repos.deletedNodes
          .replace("{count}", String(result.deleted_nodes))
          .replace("{repo}", repo),
      );
      refetch();
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError) || t.repos.deleteFailed);
    }
  }

  async function handleSyncAndWiki(repo: string, gitUrl?: string) {
    if (syncingRepo) return;
    setSyncingRepo(repo);
    try {
      const res = await syncRepoAndWiki({
        repository: repo,
        git_url: gitUrl,
      });
      const pullStatus = typeof res.git_pull === "string" ? res.git_pull : "updated";
      if (pullStatus === "already_up_to_date") {
        toast("info", `${repo}: already up to date`);
      } else {
        const nodeCount = res.index_stats?.nodes ?? 0;
        const wikiMsg = res.wiki_triggered ? ", wiki regeneration started" : "";
        toast("success", `${repo}: synced (${nodeCount} nodes indexed${wikiMsg})`);
      }
      refetch();
    } catch (err) {
      toast("error", getErrorMessage(err, "Sync failed"));
    } finally {
      setSyncingRepo(null);
    }
  }

  const repos = filteredRepos;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
            <FolderGit2 size={20} /> {t.repos.title}
          </h2>
          <div className="mt-2 flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <Building2 size={16} className="shrink-0 text-gray-400 dark:text-gray-500" aria-hidden />
            <span>
              <span className="text-gray-500 dark:text-gray-500">{t.repos.currentBusinessContext}: </span>
              <span className="font-medium text-gray-800 dark:text-gray-200">{currentBizName}</span>
            </span>
          </div>
        </div>
        <span className="text-xs text-gray-400 dark:text-gray-500 sm:self-start sm:pt-1">
          {repos.length} {t.repos.repoCount}
        </span>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
          {getErrorMessage(error, t.common.unexpectedError)}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/80">
            <tr>
              <th className="px-5 py-3 font-medium text-gray-500 dark:text-gray-400">{t.repos.repository}</th>
              <th className="px-5 py-3 font-medium text-gray-500 dark:text-gray-400">{t.repos.nodes}</th>
              <th className="px-5 py-3 text-right font-medium text-gray-500 dark:text-gray-400">{t.repos.actions}</th>
            </tr>
          </thead>
          <tbody>
            {tableLoading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <tr key={i} className="border-b border-gray-200/80 dark:border-gray-800">
                  <td className="px-5 py-3">
                    <SkeletonLine className="h-4 w-48" />
                  </td>
                  <td className="px-5 py-3">
                    <SkeletonLine className="h-4 w-12" />
                  </td>
                  <td className="px-5 py-3">
                    <SkeletonLine className="ml-auto h-4 w-16" />
                  </td>
                </tr>
              ))
            ) : repos.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-5 py-10 text-center text-gray-400 dark:text-gray-500">
                  {t.repos.noRepos}
                </td>
              </tr>
            ) : (
              repos.map((r) => (
                <tr
                  key={r.repository}
                  className="border-b border-gray-200/80 transition-colors hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/50"
                >
                  <td className="px-5 py-3 font-medium text-gray-700 dark:text-gray-200">
                    {r.repository}
                  </td>
                  <td className="px-5 py-3 text-gray-500 dark:text-gray-400">{r.nodes}</td>
                  <td className="px-5 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {isAdmin && (
                        <button
                          onClick={() => handleSyncAndWiki(r.repository, r.git_url)}
                          disabled={syncingRepo === r.repository}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-700 transition-colors hover:bg-sky-100 disabled:opacity-50 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-400 dark:hover:bg-sky-950/60"
                          title="Update code & regenerate wiki"
                        >
                          {syncingRepo === r.repository ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <RefreshCw size={12} />
                          )}
                          Sync & Wiki
                        </button>
                      )}
                      {isAdmin && (
                        <button
                          onClick={() => handleDelete(r.repository)}
                          disabled={deleteMutation.isPending}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-100 disabled:opacity-50 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-400 dark:hover:bg-red-950/60"
                        >
                          {deleteMutation.isPending ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <Trash2 size={12} />
                          )}
                          {t.repos.delete}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
