import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Search } from "lucide-react";
import { useWikiGlobalSearch } from "../../hooks/useWikiGlobalSearch";
import type { WikiSearchResult } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";
import { wikiHref } from "./wikiRouteHelpers";
import { getErrorMessage } from "../../utils/errorUtils";

function repoFilterBody(repositories: string[] | null | undefined): string[] | null | undefined {
  if (repositories === undefined) return undefined;
  if (repositories === null) return null;
  return repositories.length > 0 ? repositories : null;
}

function scopeKey(repositories: string[] | null | undefined): string {
  if (repositories === undefined) return "*";
  if (repositories === null || repositories.length === 0) return "all";
  return repositories.slice().sort().join("|");
}

type Props = {
  /** When set (e.g. from ``?q=`` on wiki index), run one global search and optionally clear the param. */
  urlQuery?: string;
  onConsumeUrlQuery?: () => void;
  /**
   * When set (unified search page), the input and server requests follow this string from the router.
   * Submitting the form calls `onLinkedSearch` so the parent can persist `q` in the URL.
   */
  linkedQuery?: string;
  onLinkedSearch?: (query: string) => void;
  /** Limit search to these repositories; null/undefined = all indexed repos. */
  repositories?: string[] | null;
  showIntro?: boolean;
  className?: string;
};

export default function WikiGlobalSearchBar({
  urlQuery,
  onConsumeUrlQuery,
  linkedQuery,
  onLinkedSearch,
  repositories,
  showIntro = true,
  className = "",
}: Props) {
  const { t } = useI18n();
  const { mutate, isPending, isSuccess, isError, data, error } = useWikiGlobalSearch();
  const [q, setQ] = useState("");
  const urlHandledKey = useRef<string | null>(null);
  const linkedHandledKey = useRef<string | null>(null);
  const repoPayload = useMemo(() => repoFilterBody(repositories ?? undefined), [repositories]);
  const rKey = scopeKey(repositories ?? undefined);

  const linkedMode = onLinkedSearch !== undefined;

  useEffect(() => {
    if (linkedMode) {
      const qFromUrl = linkedQuery ?? "";
      const raw = qFromUrl.trim();
      setQ(qFromUrl);
      if (!raw) {
        linkedHandledKey.current = null;
        return;
      }
      const dedupe = `${raw}\n${rKey}`;
      if (linkedHandledKey.current === dedupe) return;
      linkedHandledKey.current = dedupe;
      mutate({ query: raw, repositories: repoPayload });
      return;
    }

    const raw = (urlQuery ?? "").trim();
    if (!raw) {
      urlHandledKey.current = null;
      return;
    }
    const dedupe = `${raw}\n${rKey}`;
    if (urlHandledKey.current === dedupe) return;
    urlHandledKey.current = dedupe;
    setQ(raw);
    mutate({ query: raw, repositories: repoPayload });
    onConsumeUrlQuery?.();
  }, [linkedMode, linkedQuery, urlQuery, onConsumeUrlQuery, mutate, repoPayload, rKey]);

  const byRepo = data?.by_repository ?? {};
  const groups = Object.entries(byRepo).filter(([, hits]) => hits.length > 0);

  const outerClass = [
    "rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={outerClass}>
      {showIntro && (
        <>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            {t.wiki.globalSearchHeading}
          </h3>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{t.wiki.globalSearchDescription}</p>
        </>
      )}

      <form
        className={showIntro ? "mt-4" : "mt-0"}
        onSubmit={(e) => {
          e.preventDefault();
          const query = q.trim();
          if (!query) return;
          mutate({ query, repositories: repoPayload });
          if (linkedMode && onLinkedSearch) {
            linkedHandledKey.current = `${query}\n${rKey}`;
            onLinkedSearch(query);
          }
        }}
      >
        <label className="sr-only" htmlFor="wiki-global-search">
          {t.wiki.globalSearchLabel}
        </label>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
          <input
            id="wiki-global-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t.wiki.globalSearchPlaceholder}
            className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none ring-sky-500/30 placeholder:text-gray-400 focus:border-sky-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-700"
          />
          <button
            type="submit"
            disabled={isPending}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-500 dark:hover:bg-sky-400"
          >
            {isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                {t.wiki.globalSearchSearching}
              </>
            ) : (
              <>
                <Search className="size-4" aria-hidden />
                {t.wiki.globalSearchSubmit}
              </>
            )}
          </button>
        </div>
      </form>

      {data && data.partial_errors.length > 0 && (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
          {t.wiki.globalSearchPartialErrors.replace("{count}", String(data.partial_errors.length))}
        </p>
      )}

      {isError && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{getErrorMessage(error)}</p>
      )}

      {isSuccess && data && data.total === 0 && !isPending && (
        <p className="mt-4 text-sm text-gray-600 dark:text-gray-400">{t.wiki.globalSearchNoResults}</p>
      )}

      {groups.length > 0 && (
        <div className="mt-5 space-y-5 border-t border-gray-100 pt-4 dark:border-gray-700">
          {groups.map(([repository, hits]) => (
            <section key={repository}>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                {t.wiki.globalSearchRepositoryGroup.replace("{repository}", repository)}
              </h4>
              <ul className="mt-2 space-y-1">
                {hits.map((r: WikiSearchResult) => (
                  <li key={`${repository}:${r.page_path}`}>
                    <Link
                      to={wikiHref(r.page_path)}
                      className="block rounded-lg border border-transparent px-3 py-2 transition-colors hover:border-sky-200 hover:bg-sky-50/60 dark:hover:border-sky-900 dark:hover:bg-sky-950/40"
                    >
                      <span className="font-medium text-gray-900 dark:text-gray-100">{r.title}</span>
                      <span className="mt-0.5 block truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">
                        {r.page_path}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
