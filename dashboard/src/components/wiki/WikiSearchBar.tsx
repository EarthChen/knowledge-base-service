import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Search } from "lucide-react";
import FocusTrap from "../FocusTrap";
import { useWikiSemanticSearch } from "../../hooks/useWikiSearch";
import { useI18n } from "../../i18n/context";
import { wikiSearchOptionId } from "./WikiSearchResults";
import WikiSemanticSearchResults, { semanticSearchResultCount } from "./WikiSemanticSearchResults";
import { wikiHref } from "./wikiRouteHelpers";
import { getErrorMessage } from "../../utils/errorUtils";

const WIKI_SEARCH_RESULTS_LIST_ID = "wiki-search-results-listbox";

const isMac =
  typeof navigator !== "undefined" && /mac/i.test(navigator.platform || navigator.userAgent);
const shortcutHint = isMac ? "⌘K" : "Ctrl+K";

type Props = {
  linkParams?: Record<string, string>;
  /** Repository scope for POST /wiki/semantic-search (falls back to business id). */
  repository: string;
};

export default function WikiSearchBar({ linkParams, repository }: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const { mutate, isPending, isError, error, isSuccess, data } = useWikiSemanticSearch();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const repoTrimmed = repository.trim() || (linkParams?.business_id ?? "").trim() || "default";

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((isMac ? e.metaKey : e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        e.stopImmediatePropagation();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, []);

  useEffect(() => {
    if (!open) return;
    const raw = query.trim();
    if (!raw) {
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      mutate({ query: raw, repository: repoTrimmed, limit: 20 });
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [open, query, mutate, repoTrimmed]);

  const totalHits =
    data != null
      ? semanticSearchResultCount(data.wiki_hits ?? [], data.entity_hits ?? [], data.call_chain_hits ?? [])
      : 0;

  useEffect(() => {
    if (totalHits === 0) {
      setActiveIndex(-1);
      return;
    }
    setActiveIndex((i) => (i >= 0 && i < totalHits ? i : 0));
  }, [totalHits]);

  const close = useCallback(() => setOpen(false), []);

  const listPopupOpen =
    open && query.trim().length > 0 && (isPending || isError || isSuccess);
  const hasResultOptions = Boolean(totalHits > 0 && query.trim());

  const onSelect = useCallback(
    (path: string, repoForHit?: string) => {
      const params = repoForHit
        ? { ...linkParams, repo: repoForHit }
        : linkParams;
      navigate(wikiHref(path, params));
      setOpen(false);
      setQuery("");
    },
    [navigate, linkParams],
  );

  const wikiHitCount = data?.wiki_hits?.length ?? 0;

  const canNavigateResults = hasResultOptions && totalHits > 0;

  const onSearchKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLInputElement>) => {
      if (!canNavigateResults || !data) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => {
          const next = i < 0 ? 0 : i + 1;
          return next >= totalHits ? 0 : next;
        });
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => {
          const next = i < 0 ? totalHits - 1 : i - 1;
          return next < 0 ? totalHits - 1 : next;
        });
        return;
      }
      if (e.key === "Enter" && activeIndex >= 0 && activeIndex < wikiHitCount) {
        e.preventDefault();
        const hit = data.wiki_hits[activeIndex];
        if (hit) onSelect(hit.page_path, repoTrimmed);
      }
    },
    [canNavigateResults, totalHits, activeIndex, data, wikiHitCount, onSelect, repoTrimmed],
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
          {shortcutHint}
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
              onKeyDown={onSearchKeyDown}
              placeholder={t.wiki.searchPlaceholder}
              className="min-w-0 flex-1 border-0 bg-transparent py-3 text-sm text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100"
              role="combobox"
              aria-expanded={listPopupOpen}
              aria-controls={hasResultOptions ? WIKI_SEARCH_RESULTS_LIST_ID : undefined}
              aria-autocomplete="list"
              aria-activedescendant={
                hasResultOptions && activeIndex >= 0
                  ? wikiSearchOptionId(WIKI_SEARCH_RESULTS_LIST_ID, activeIndex)
                  : undefined
              }
            />
            {isPending ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-gray-400" aria-hidden />
            ) : null}
          </div>
          {isError && (
            <p className="px-3 py-2 text-sm text-red-600 dark:text-red-400">
              {getErrorMessage(error, t.common.unexpectedError)}
            </p>
          )}
          {data && query.trim() && (
            <WikiSemanticSearchResults
              listboxId={WIKI_SEARCH_RESULTS_LIST_ID}
              wikiHits={data.wiki_hits ?? []}
              entityHits={data.entity_hits ?? []}
              callChainHits={data.call_chain_hits ?? []}
              searchRepository={repoTrimmed}
              activeIndex={activeIndex}
              highlightQuery={query.trim()}
              onWikiSelect={(path, repo) => onSelect(path, repo)}
              sectionWiki={t.wiki.semanticSearchSectionWiki}
              sectionEntities={t.wiki.semanticSearchSectionEntities}
              sectionChains={t.wiki.semanticSearchSectionCallChains}
            />
          )}
          {isSuccess && data && totalHits === 0 && query.trim() && (
            <p className="px-3 py-4 text-sm text-gray-500 dark:text-gray-400">
              {t.wiki.globalSearchNoResults}
            </p>
          )}
        </div>
      </FocusTrap>
    </div>
  );
}
