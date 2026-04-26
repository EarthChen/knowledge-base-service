import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronUp, Layers, Network } from "lucide-react";
import {
  useArchitectureSearch,
  useP2Stats,
  useRepositories,
} from "../api/hooks";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { SkeletonLine } from "../components/Skeleton";

const PAGE_SIZE = 30;

function layerBadgeClasses(layer: string): string {
  const k = layer.toLowerCase();
  if (k.includes("presentation")) {
    return "bg-sky-100 text-sky-800 border-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:border-sky-800";
  }
  if (k.includes("business") || k === "biz") {
    return "bg-violet-100 text-violet-800 border-violet-200 dark:bg-violet-950/50 dark:text-violet-300 dark:border-violet-800";
  }
  if (k.includes("model")) {
    return "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800";
  }
  if (k.includes("data_access") || k.includes("data access") || k === "data") {
    return "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800";
  }
  if (k.includes("infrastructure") || k.includes("infra")) {
    return "bg-slate-100 text-slate-800 border-slate-200 dark:bg-slate-900/60 dark:text-slate-300 dark:border-slate-700";
  }
  if (k.includes("rpc")) return "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950/50 dark:text-blue-300 dark:border-blue-800";
  if (k.includes("messaging") || k.includes("msg")) {
    return "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-950/50 dark:text-orange-300 dark:border-orange-800";
  }
  if (k.includes("unknown")) {
    return "bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600";
  }
  return "bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-800/80 dark:text-gray-300 dark:border-gray-600";
}

export default function ArchitecturePage() {
  const { t, locale } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();

  const { data: p2, isLoading: p2Loading } = useP2Stats();
  const { data: reposData } = useRepositories();

  const layersSorted = useMemo(() => {
    if (!p2?.architecture_layers) return [] as [string, number][];
    return Object.entries(p2.architecture_layers).sort((a, b) => b[1] - a[1]);
  }, [p2]);

  const defaultLayer = layersSorted[0]?.[0] ?? "";

  const layerFromUrl = searchParams.get("layer");
  const activeLayer = layerFromUrl || defaultLayer;

  useEffect(() => {
    if (!p2 || layerFromUrl || !defaultLayer) return;
    setSearchParams({ layer: defaultLayer }, { replace: true });
  }, [p2, layerFromUrl, defaultLayer, setSearchParams]);

  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const tId = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(tId);
  }, [searchInput]);

  const [repositoryFilter, setRepositoryFilter] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    setPage(1);
  }, [activeLayer, debouncedSearch, repositoryFilter]);

  const offset = (page - 1) * PAGE_SIZE;

  const { data: searchData, isLoading: tableLoading, error: searchError } =
    useArchitectureSearch(activeLayer, {
      repository: repositoryFilter || undefined,
      search: debouncedSearch || undefined,
      offset,
      limit: PAGE_SIZE,
    });

  const totalCount =
    searchData?.total_count ?? searchData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const toggleExpanded = useCallback((uid: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }, []);

  const selectLayer = (name: string) => {
    setSearchParams({ layer: name });
  };

  const repos = reposData?.repositories ?? [];

  const pageLabel =
    locale === "zh"
      ? `${t.architecture.page} ${page} ${t.architecture.of} ${totalPages} 页`
      : `${t.architecture.page} ${page} ${t.architecture.of} ${totalPages}`;

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
        <Layers size={20} className="text-sky-600 dark:text-sky-400" />
        {t.architecture.title}
      </h2>

      <p className="text-sm text-gray-600 dark:text-gray-400">
        <Link
          to="/wiki?tool=insights"
          className="inline-flex items-center gap-1.5 font-medium text-sky-700 underline decoration-sky-200 hover:text-sky-900 dark:text-sky-400 dark:decoration-sky-800 dark:hover:text-sky-300"
        >
          <Network size={16} className="shrink-0 text-violet-600 dark:text-violet-400" aria-hidden />
          {t.architecture.graphInsightsLink}
        </Link>
        <span className="text-gray-400 dark:text-gray-500">{t.architecture.graphInsightsBlurb}</span>
      </p>

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <aside className="w-full shrink-0 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900 lg:w-56">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {t.architecture.layers}
          </p>
          {p2Loading && !p2 ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <SkeletonLine key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : layersSorted.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-gray-500">—</p>
          ) : (
            <ul className="space-y-1.5">
              {layersSorted.map(([name, count]) => {
                const selected = activeLayer === name;
                return (
                  <li key={name}>
                    <button
                      type="button"
                      onClick={() => selectLayer(name)}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-2 text-left text-sm transition-colors ${
                        selected
                          ? "border-sky-200 bg-sky-100 text-sky-700 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-300"
                          : "border-transparent bg-gray-50 text-gray-700 hover:bg-gray-100 dark:bg-gray-800/60 dark:text-gray-300 dark:hover:bg-gray-800"
                      }`}
                    >
                      <span
                        className={`inline-flex max-w-[65%] items-center truncate rounded-md border px-1.5 py-0.5 text-xs font-medium ${layerBadgeClasses(name)}`}
                      >
                        {name}
                      </span>
                      <span className="shrink-0 tabular-nums text-xs text-gray-500 dark:text-gray-400">{count}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <div className="min-w-0 flex-1 space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder={t.architecture.searchPlaceholder}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-400 dark:focus:ring-sky-600 sm:max-w-xs"
            />
            <select
              value={repositoryFilter}
              onChange={(e) => setRepositoryFilter(e.target.value)}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-sky-400 dark:focus:ring-sky-600 sm:w-56"
            >
              <option value="">{t.architecture.allRepositories}</option>
              {repos.map((r) => (
                <option key={r.repository} value={r.repository}>
                  {r.repository}
                </option>
              ))}
            </select>
          </div>

          {searchError && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
              {getErrorMessage(searchError)}
            </div>
          )}

          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/80">
                <tr>
                  <th className="w-8 px-2 py-3" aria-hidden />
                  <th className="px-3 py-3 font-medium text-gray-500 dark:text-gray-400">{t.architecture.name}</th>
                  <th className="px-3 py-3 font-medium text-gray-500 dark:text-gray-400">{t.architecture.fqn}</th>
                  <th className="px-3 py-3 font-medium text-gray-500 dark:text-gray-400">
                    {t.architecture.repository}
                  </th>
                  <th className="px-3 py-3 font-medium text-gray-500 dark:text-gray-400">
                    {t.architecture.semanticRoles}
                  </th>
                  <th className="px-3 py-3 text-right font-medium text-gray-500 dark:text-gray-400">
                    {t.architecture.methodCount}
                  </th>
                </tr>
              </thead>
              <tbody>
                {!activeLayer ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-10 text-center text-gray-400 dark:text-gray-500">
                      {p2Loading ? t.architecture.loading : "—"}
                    </td>
                  </tr>
                ) : tableLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="px-2 py-3" />
                      <td className="px-3 py-3">
                        <SkeletonLine className="h-4 w-32" />
                      </td>
                      <td className="px-3 py-3">
                        <SkeletonLine className="h-4 w-48" />
                      </td>
                      <td className="px-3 py-3">
                        <SkeletonLine className="h-4 w-28" />
                      </td>
                      <td className="px-3 py-3">
                        <SkeletonLine className="h-4 w-24" />
                      </td>
                      <td className="px-3 py-3 text-right">
                        <SkeletonLine className="ml-auto h-4 w-8" />
                      </td>
                    </tr>
                  ))
                ) : (searchData?.classes?.length ?? 0) === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-10 text-center text-gray-400 dark:text-gray-500">
                      {t.architecture.noClasses}
                    </td>
                  </tr>
                ) : (
                  searchData!.classes.map((row) => {
                    const isOpen = expanded.has(row.uid);
                    const methodCount = row.methods?.length ?? 0;
                    return (
                      <Fragment key={row.uid}>
                        <tr
                          {...(methodCount > 0 ? {
                            role: "button",
                            tabIndex: 0,
                            "aria-expanded": isOpen,
                            onClick: () => toggleExpanded(row.uid),
                            onKeyDown: (e: React.KeyboardEvent) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                toggleExpanded(row.uid);
                              }
                            },
                          } : {})}
                          className={`border-b border-gray-100 transition-colors hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/50 ${methodCount > 0 ? "cursor-pointer focus-visible:outline-2 focus-visible:outline-sky-500 focus-visible:outline-offset-[-2px] dark:focus-visible:outline-sky-400" : ""}`}
                        >
                          <td className="px-2 py-2.5 align-middle text-gray-400 dark:text-gray-500">
                            {methodCount > 0 ? (
                              isOpen ? (
                                <ChevronUp size={16} className="mx-auto" />
                              ) : (
                                <ChevronDown size={16} className="mx-auto" />
                              )
                            ) : null}
                          </td>
                          <td className="px-3 py-2.5 font-medium text-gray-900 dark:text-gray-100">{row.name}</td>
                          <td className="max-w-xs truncate px-3 py-2.5 font-mono text-xs text-gray-600 dark:text-gray-400">
                            {row.fqn ?? "—"}
                          </td>
                          <td className="max-w-[200px] truncate px-3 py-2.5 text-gray-600 dark:text-gray-400">
                            {row.repository ?? "—"}
                          </td>
                          <td className="max-w-[180px] px-3 py-2.5 text-xs text-gray-600 dark:text-gray-400">
                            {row.semantic_roles?.length
                              ? row.semantic_roles.join(", ")
                              : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-right tabular-nums text-gray-700 dark:text-gray-300">
                            {methodCount}
                          </td>
                        </tr>
                        {isOpen && methodCount > 0 && (
                          <tr className="border-b border-gray-100 bg-gray-50/80 dark:border-gray-800 dark:bg-gray-800/40">
                            <td colSpan={6} className="px-3 pb-4 pt-0">
                              <p className="mb-2 pl-7 text-xs font-medium text-gray-500 dark:text-gray-400">
                                {t.architecture.methods}
                              </p>
                              <ul className="space-y-2 pl-7">
                                {row.methods.map((m) => (
                                  <li
                                    key={m.uid}
                                    className="rounded-lg border border-gray-200 bg-white p-2.5 text-xs dark:border-gray-600 dark:bg-gray-900"
                                  >
                                    <div className="font-medium text-gray-800 dark:text-gray-100">{m.name}</div>
                                    <div className="mt-1 font-mono text-[11px] leading-relaxed text-gray-600 dark:text-gray-400">
                                      <span className="text-gray-400 dark:text-gray-500">{t.architecture.signature}: </span>
                                      {m.signature}
                                    </div>
                                  </li>
                                ))}
                              </ul>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {activeLayer && !tableLoading && totalCount > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-gray-600 dark:text-gray-400">
              <span className="tabular-nums">{pageLabel}</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  {t.architecture.prev}
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  {t.architecture.next}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
