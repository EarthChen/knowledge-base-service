import { FolderGit2, Trash2, Loader2 } from "lucide-react";
import { useRepositories, useDeleteRepository } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useAuth } from "../contexts/AuthContext";
import { useToast } from "../components/Toast";
import { SkeletonLine } from "../components/Skeleton";

export default function Repositories() {
  const { data, isLoading, error, refetch } = useRepositories();
  const deleteMutation = useDeleteRepository();
  const { t } = useI18n();
  const { toast } = useToast();
  const { isAdmin } = useAuth();

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
      toast("error", (err as Error).message || t.repos.deleteFailed);
    }
  }

  const repos = data?.repositories ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <FolderGit2 size={20} /> {t.repos.title}
        </h2>
        <span className="text-xs text-gray-400">
          {repos.length} {t.repos.repoCount}
        </span>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {(error as Error).message}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50">
            <tr>
              <th className="px-5 py-3 font-medium text-gray-500">{t.repos.repository}</th>
              <th className="px-5 py-3 font-medium text-gray-500">{t.repos.nodes}</th>
              <th className="px-5 py-3 text-right font-medium text-gray-500">{t.repos.actions}</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <tr key={i} className="border-b border-gray-200/80">
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
                <td colSpan={3} className="px-5 py-10 text-center text-gray-400">
                  {t.repos.noRepos}
                </td>
              </tr>
            ) : (
              repos.map((r) => (
                <tr
                  key={r.repository}
                  className="border-b border-gray-200/80 transition-colors hover:bg-gray-50"
                >
                  <td className="px-5 py-3 font-medium text-gray-700">
                    {r.repository}
                  </td>
                  <td className="px-5 py-3 text-gray-500">{r.nodes}</td>
                  <td className="px-5 py-3 text-right">
                    {isAdmin && (
                      <button
                        onClick={() => handleDelete(r.repository)}
                        disabled={deleteMutation.isPending}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-100 disabled:opacity-50"
                      >
                        {deleteMutation.isPending ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Trash2 size={12} />
                        )}
                        {t.repos.delete}
                      </button>
                    )}
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
