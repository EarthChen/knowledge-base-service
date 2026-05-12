import { useState, type FormEvent } from "react";
import { Loader2, Pencil, Pin, Trash2, X } from "lucide-react";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import {
  useDeleteDomain,
  useDomainList,
  usePinModule,
  usePinnedModules,
  useUnpinModule,
  useUpsertDomain,
} from "../../hooks/useDomainManagement";

type Props = {
  businessId: string;
};

export default function DomainManagement({ businessId }: Props) {
  const { t } = useI18n();
  const domainQuery = useDomainList(businessId);
  const pinnedQuery = usePinnedModules(businessId);
  const upsertDomain = useUpsertDomain(businessId);
  const deleteDomain = useDeleteDomain(businessId);
  const pinModule = usePinModule(businessId);
  const unpinModule = useUnpinModule(businessId);

  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");

  const [pinModuleName, setPinModuleName] = useState("");
  const [pinDomainSlug, setPinDomainSlug] = useState("");

  const domains = domainQuery.data ?? [];
  const pinned = pinnedQuery.data ?? [];

  const startEdit = (slug: string, displayName: string) => {
    setEditingSlug(slug);
    setEditDisplayName(displayName);
  };

  const cancelEdit = () => {
    setEditingSlug(null);
    setEditDisplayName("");
  };

  const saveEdit = () => {
    const slug = editingSlug;
    if (!slug?.trim()) return;
    upsertDomain.mutate(
      { slug, displayName: editDisplayName.trim() || slug },
      { onSuccess: () => cancelEdit() },
    );
  };

  const handleDelete = (slug: string, displayName: string) => {
    const ok = window.confirm(
      `Delete domain anchor "${displayName}" (${slug})? Pinned modules for this domain may need review.`,
    );
    if (!ok) return;
    deleteDomain.mutate(slug);
  };

  const handlePinSubmit = (e: FormEvent) => {
    e.preventDefault();
    const moduleName = pinModuleName.trim();
    const domainSlug = pinDomainSlug.trim();
    if (!moduleName || !domainSlug) return;
    pinModule.mutate(
      { moduleName, domainSlug },
      {
        onSuccess: () => {
          setPinModuleName("");
          setPinDomainSlug("");
        },
      },
    );
  };

  const pending =
    domainQuery.isLoading ||
    pinnedQuery.isLoading ||
    upsertDomain.isPending ||
    deleteDomain.isPending ||
    pinModule.isPending ||
    unpinModule.isPending;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">Domain anchors</h3>
        {domainQuery.isLoading && (
          <p className="text-sm text-gray-500 dark:text-gray-400" role="status">
            {t.common.loading}
          </p>
        )}
        {domainQuery.isError && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {getErrorMessage(domainQuery.error, t.common.unexpectedError)}
          </p>
        )}
        {!domainQuery.isLoading && !domainQuery.isError && domains.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">No domain anchors yet.</p>
        )}
        {domains.length > 0 && (
          <div className="max-h-[min(50vh,420px)] overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full min-w-[480px] text-left text-sm">
              <thead className="sticky top-0 bg-gray-50 text-xs uppercase tracking-wide text-gray-500 dark:bg-gray-800/90 dark:text-gray-400">
                <tr>
                  <th className="px-3 py-2">Slug</th>
                  <th className="px-3 py-2">Display name</th>
                  <th className="px-3 py-2 text-right">Modules</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {domains.map((row) => (
                  <tr key={row.slug} className="bg-white/90 dark:bg-gray-900/90">
                    <td className="px-3 py-2 font-mono text-xs text-gray-800 dark:text-gray-200">{row.slug}</td>
                    <td className="px-3 py-2">
                      {editingSlug === row.slug ? (
                        <input
                          type="text"
                          value={editDisplayName}
                          onChange={(e) => setEditDisplayName(e.target.value)}
                          className="w-full rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 shadow-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                          aria-label="Display name"
                        />
                      ) : (
                        <span className="text-gray-900 dark:text-gray-100">{row.display_name}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-gray-600 dark:text-gray-400">
                      {row.module_count}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap justify-end gap-1">
                        {editingSlug === row.slug ? (
                          <>
                            <button
                              type="button"
                              onClick={saveEdit}
                              disabled={upsertDomain.isPending}
                              className="inline-flex items-center gap-1 rounded-md bg-sky-600 px-2 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {upsertDomain.isPending ? (
                                <Loader2 size={12} className="animate-spin" aria-hidden />
                              ) : null}
                              Save
                            </button>
                            <button
                              type="button"
                              onClick={cancelEdit}
                              className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => startEdit(row.slug, row.display_name)}
                              disabled={!!pending && editingSlug !== row.slug}
                              className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800 disabled:opacity-50"
                            >
                              <Pencil size={12} aria-hidden />
                              Edit
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDelete(row.slug, row.display_name)}
                              disabled={deleteDomain.isPending}
                              className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 dark:border-red-900/40 dark:text-red-400 dark:hover:bg-red-950/30"
                            >
                              <Trash2 size={12} aria-hidden />
                              Delete
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(upsertDomain.isError || deleteDomain.isError) && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400" role="alert">
            {getErrorMessage(upsertDomain.error ?? deleteDomain.error, t.common.unexpectedError)}
          </p>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
        <div className="mb-3 flex items-center gap-2">
          <Pin size={16} className="text-sky-600 dark:text-sky-400" aria-hidden />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Pinned modules</h3>
        </div>
        {pinnedQuery.isError && (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {getErrorMessage(pinnedQuery.error, t.common.unexpectedError)}
          </p>
        )}
        {!pinnedQuery.isError && pinned.length === 0 && !pinnedQuery.isLoading && (
          <p className="text-xs text-gray-500 dark:text-gray-400">No modules pinned.</p>
        )}
        {pinnedQuery.isLoading && (
          <p className="text-xs text-gray-500 dark:text-gray-400" role="status">
            {t.common.loading}
          </p>
        )}
        {pinned.length > 0 && (
          <ul className="space-y-2">
            {pinned.map((p) => (
              <li
                key={p.module_name}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2 text-sm dark:border-gray-800 dark:bg-gray-900/50"
              >
                <div>
                  <span className="font-mono text-xs text-gray-900 dark:text-gray-100">{p.module_name}</span>
                  <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">→ {p.domain_slug}</span>
                </div>
                <button
                  type="button"
                  onClick={() => unpinModule.mutate(p.module_name)}
                  disabled={unpinModule.isPending}
                  className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-white dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                >
                  <X size={12} aria-hidden />
                  Unpin
                </button>
              </li>
            ))}
          </ul>
        )}
        {(pinModule.isError || unpinModule.isError) && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400" role="alert">
            {getErrorMessage(pinModule.error ?? unpinModule.error, t.common.unexpectedError)}
          </p>
        )}

        <form onSubmit={handlePinSubmit} className="mt-4 space-y-3 border-t border-gray-100 pt-4 dark:border-gray-800">
          <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Pin a module</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
            <label className="block min-w-[12rem] flex-1 text-xs">
              <span className="mb-1 block text-gray-600 dark:text-gray-400">Module name</span>
              <input
                type="text"
                value={pinModuleName}
                onChange={(e) => setPinModuleName(e.target.value)}
                placeholder="e.g. my_service"
                className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 shadow-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
              />
            </label>
            <label className="block min-w-[12rem] flex-1 text-xs">
              <span className="mb-1 block text-gray-600 dark:text-gray-400">Domain</span>
              <select
                value={pinDomainSlug}
                onChange={(e) => setPinDomainSlug(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 shadow-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
              >
                <option value="">Select domain…</option>
                {domains.map((d) => (
                  <option key={d.slug} value={d.slug}>
                    {d.display_name} ({d.slug})
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              disabled={pinModule.isPending || !pinModuleName.trim() || !pinDomainSlug.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {pinModule.isPending ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Pin size={16} aria-hidden />}
              Pin module
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
