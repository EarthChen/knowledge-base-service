import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Search } from "lucide-react";
import { useWikiGlobalSearch } from "../../hooks/useWikiGlobalSearch";
import type { WikiSearchResult } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";

function wikiHref(repository: string, path: string): string {
  const er = encodeURIComponent(repository);
  const ep = path
    .split("/")
    .filter(Boolean)
    .map((s) => encodeURIComponent(s))
    .join("/");
  return `/wiki/${er}/${ep}`;
}

type Props = {
  /** When set (e.g. from ``?q=``), run one global search and notify parent to clear the param. */
  urlQuery?: string;
  onConsumeUrlQuery?: () => void;
};

export default function WikiGlobalSearchBar({ urlQuery, onConsumeUrlQuery }: Props) {
  const { t } = useI18n();
  const { mutate, isPending, isSuccess, isError, data, error } = useWikiGlobalSearch();
  const [q, setQ] = useState("");
  const urlHandled = useRef(false);

  useEffect(() => {
    const raw = (urlQuery ?? "").trim();
    if (!raw) {
      urlHandled.current = false;
      return;
    }
    if (urlHandled.current) return;
    urlHandled.current = true;
    setQ(raw);
    mutate({ query: raw });
    onConsumeUrlQuery?.();
  }, [urlQuery, onConsumeUrlQuery, mutate]);

  const byRepo = data?.by_repository ?? {};
  const groups = Object.entries(byRepo).filter(([, hits]) => hits.length > 0);

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        {t.wiki.globalSearchHeading}
      </h3>
      <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{t.wiki.globalSearchDescription}</p>

      <form
        className="mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          const query = q.trim();
          if (!query) return;
          mutate({ query });
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
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{(error as Error).message}</p>
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
                      to={wikiHref(repository, r.page_path)}
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
