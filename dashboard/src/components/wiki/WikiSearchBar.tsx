import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Search } from "lucide-react";
import FocusTrap from "../FocusTrap";
import { useWikiSearch } from "../../hooks/useWikiSearch";
import { useI18n } from "../../i18n/context";
import WikiSearchResults from "./WikiSearchResults";
import { wikiHref } from "./wikiRouteHelpers";

type Props = {
  repository: string;
  linkParams?: Record<string, string>;
};

function getErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function WikiSearchBar({ repository, linkParams }: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const { mutate, isPending, isError, error, isSuccess, data } = useWikiSearch();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    const raw = query.trim();
    if (!raw || !repository.trim()) {
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      mutate({ repository, query: raw });
    }, 280);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [open, query, repository, mutate]);

  const close = useCallback(() => setOpen(false), []);

  const onSelect = useCallback(
    (path: string) => {
      navigate(wikiHref(path, linkParams));
      setOpen(false);
      setQuery("");
    },
    [navigate, linkParams],
  );

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-600 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
      >
        <Search size={14} aria-hidden />
        <span className="hidden sm:inline">{t.wiki.searchWikiLabel}</span>
        <kbd className="hidden rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-[10px] text-gray-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-400 sm:inline">
          ⌘K
        </kbd>
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <FocusTrap onEscape={close}>
        <div
          className="w-full max-w-lg overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-900"
          role="dialog"
          aria-modal="true"
          aria-label={t.wiki.searchWikiLabel}
        >
          <div className="flex items-center gap-2 border-b border-gray-100 px-3 dark:border-gray-700">
            <Search size={18} className="shrink-0 text-gray-400" aria-hidden />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.wiki.searchPlaceholder}
              className="min-w-0 flex-1 border-0 bg-transparent py-3 text-sm text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100"
              aria-autocomplete="list"
            />
            {isPending ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-gray-400" aria-hidden />
            ) : null}
          </div>
          {isError && (
            <p className="px-3 py-2 text-sm text-red-600 dark:text-red-400">
              {getErrorMessage(error)}
            </p>
          )}
          {data && query.trim() && <WikiSearchResults results={data.results} onSelect={onSelect} />}
          {isSuccess && data && data.results.length === 0 && query.trim() && (
            <p className="px-3 py-4 text-sm text-gray-500 dark:text-gray-400">
              {t.wiki.globalSearchNoResults}
            </p>
          )}
        </div>
      </FocusTrap>
    </div>
  );
}
