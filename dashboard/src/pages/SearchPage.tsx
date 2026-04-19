import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Zap, Brain, Clock, X, Download } from "lucide-react";
import { useHybridSearch, useRepositories } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useSearchHistory } from "../hooks/useSearchHistory";
import SearchResultCard from "../components/SearchResultCard";
import SearchResultSkeleton from "../components/SearchResultSkeleton";
import DeepSearchSection from "../components/DeepSearchSection";
import GraphContextCards from "../components/GraphContextCards";

type SearchMode = "hybrid" | "deep";

const ENTITY_TYPES = ["all", "function", "class", "module", "document"] as const;
const LANGUAGES = ["all", "python", "java", "go", "javascript", "typescript"] as const;

const PAGE_SIZE = 20;

function parseSortParam(raw: string | null): "score" | "name" | "path" {
  if (raw === "name" || raw === "path" || raw === "score") return raw;
  return "score";
}

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [entityType, setEntityType] = useState("all");
  const [repository, setRepository] = useState(() => searchParams.get("repo") ?? "all");
  const [language, setLanguage] = useState(() => searchParams.get("lang") ?? "all");
  const [k, setK] = useState(10);
  const [expandDepth, setExpandDepth] = useState(2);

  const { data: reposData } = useRepositories();
  const { history, addEntry, removeEntry } = useSearchHistory();
  const [showHistory, setShowHistory] = useState(false);
  const [highlightedHistoryIndex, setHighlightedHistoryIndex] = useState(-1);
  const historyListId = "search-history-listbox";

  const { t } = useI18n();
  const { mutate: runHybridSearch, isPending: hybridPending, data: hybridResult, error } =
    useHybridSearch();

  const sortFromUrl = parseSortParam(searchParams.get("sort"));
  const pageFromUrl = Math.max(1, Number.parseInt(searchParams.get("page") || "1", 10) || 1);

  const hybridPageLimit = hybridResult?.limit ?? PAGE_SIZE;
  const hybridTotalPages =
    hybridResult != null ? Math.max(1, Math.ceil((hybridResult.total || 0) / hybridPageLimit)) : 1;

  useEffect(() => {
    if (hybridResult != null && pageFromUrl > hybridTotalPages) {
      const params = new URLSearchParams(searchParams);
      params.set("page", String(hybridTotalPages));
      setSearchParams(params, { replace: true });
    }
  }, [hybridResult, hybridTotalPages, pageFromUrl, searchParams, setSearchParams]);

  const hybridPageIndicator =
    hybridResult != null
      ? t.search.pageIndicator
          .replace("{page}", String(Math.min(pageFromUrl, hybridTotalPages)))
          .replace("{totalPages}", String(hybridTotalPages))
      : "";

  useEffect(() => {
    const raw = searchParams.get("q") ?? "";
    const repoParam = searchParams.get("repo") ?? "all";
    const langParam = searchParams.get("lang") ?? "all";
    const pageParam = Math.max(1, Number.parseInt(searchParams.get("page") || "1", 10) || 1);
    const sortParam = parseSortParam(searchParams.get("sort"));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync URL navigation into form state
    setQuery(raw);
    setRepository(repoParam);
    setLanguage(langParam);
    const q = raw.trim();
    if (!q) return;
    runHybridSearch({
      query: q,
      k,
      expand_depth: expandDepth,
      entity_type: entityType === "all" ? undefined : entityType,
      repository: repoParam === "all" ? undefined : repoParam,
      language: langParam === "all" ? undefined : langParam,
      offset: (pageParam - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      sort_by: sortParam,
    });
  }, [searchParams, k, expandDepth, entityType, runHybridSearch]);

  useEffect(() => {
    if (!showHistory) setHighlightedHistoryIndex(-1);
  }, [showHistory]);

  const isLoading = hybridPending;

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    addEntry(query.trim());
    setShowHistory(false);
    const params = new URLSearchParams();
    params.set("q", query.trim());
    params.set("repo", repository);
    params.set("lang", language);
    params.set("page", "1");
    params.set("sort", parseSortParam(searchParams.get("sort")));
    setSearchParams(params);
  }

  const applyHistoryQuery = useCallback((h: string) => {
    setQuery(h);
    setShowHistory(false);
    setHighlightedHistoryIndex(-1);
    addEntry(h);
    const params = new URLSearchParams();
    params.set("q", h);
    params.set("repo", repository);
    params.set("lang", language);
    params.set("page", "1");
    params.set("sort", parseSortParam(searchParams.get("sort")));
    setSearchParams(params);
  }, [addEntry, repository, language, searchParams, setSearchParams]);

  const handleHistoryKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      const slice = history.slice(0, 10);
      if (!slice.length) return;

      if (e.key === "Escape") {
        if (showHistory) {
          e.preventDefault();
          setShowHistory(false);
          setHighlightedHistoryIndex(-1);
        }
        return;
      }

      if (!showHistory) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setShowHistory(true);
          setHighlightedHistoryIndex(0);
        }
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightedHistoryIndex((i) => {
          const next = i < 0 ? 0 : i + 1;
          return Math.min(slice.length - 1, next);
        });
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightedHistoryIndex((i) => Math.max(0, (i < 0 ? 0 : i) - 1));
        return;
      }

      if (e.key === "Enter") {
        const idx = highlightedHistoryIndex;
        if (idx >= 0 && slice[idx]) {
          e.preventDefault();
          applyHistoryQuery(slice[idx]);
        }
      }
    },
    [applyHistoryQuery, highlightedHistoryIndex, history, showHistory],
  );

  if (mode === "deep") {
    return (
      <div className="space-y-6">
        <h2 className="text-lg font-semibold text-gray-900">{t.search.title}</h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setMode("hybrid")}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-400 transition-colors hover:text-gray-700"
          >
            <Zap size={14} /> {t.search.hybrid}
          </button>
          <button
            type="button"
            onClick={() => setMode("deep")}
            className="flex items-center gap-1.5 rounded-lg bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-700"
          >
            <Brain size={14} /> {t.search.deep}
          </button>
        </div>
        <DeepSearchSection showTitle={false} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">{t.search.title}</h2>

      <form onSubmit={handleSearch} className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setMode("hybrid")}
            className="flex items-center gap-1.5 rounded-lg bg-purple-100 px-3 py-1.5 text-xs font-medium text-purple-600"
          >
            <Zap size={14} /> {t.search.hybrid}
          </button>
          <button
            type="button"
            onClick={() => setMode("deep")}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-400 transition-colors hover:text-gray-700"
          >
            <Brain size={14} /> {t.search.deep}
          </button>
        </div>

        <div className="relative mt-4 flex gap-3">
          <div className="relative flex-1">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => history.length > 0 && setShowHistory(true)}
              onBlur={() => setTimeout(() => setShowHistory(false), 200)}
              onKeyDown={handleHistoryKeyDown}
              placeholder={t.search.placeholder}
              aria-autocomplete="list"
              aria-expanded={showHistory && history.length > 0}
              aria-controls={history.length > 0 ? historyListId : undefined}
              aria-activedescendant={
                showHistory && highlightedHistoryIndex >= 0
                  ? `${historyListId}-opt-${highlightedHistoryIndex}`
                  : undefined
              }
              className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-300"
            />
            {showHistory && history.length > 0 && (
              <div
                id={historyListId}
                role="listbox"
                aria-label={t.search.title}
                className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg"
              >
                {history.slice(0, 10).map((h, i) => (
                  <div
                    key={h}
                    id={`${historyListId}-opt-${i}`}
                    role="option"
                    aria-selected={highlightedHistoryIndex === i}
                    className={`flex cursor-pointer items-center gap-2 px-4 py-2 text-sm hover:bg-gray-50 ${
                      highlightedHistoryIndex === i ? "bg-purple-50" : ""
                    }`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      applyHistoryQuery(h);
                    }}
                    onMouseEnter={() => setHighlightedHistoryIndex(i)}
                  >
                    <Clock size={12} className="shrink-0 text-gray-400" />
                    <span className="flex-1 truncate text-gray-700">{h}</span>
                    <button
                      type="button"
                      className="shrink-0 rounded p-0.5 text-gray-300 hover:text-gray-500"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        removeEntry(h);
                      }}
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className="rounded-lg bg-purple-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-purple-500 disabled:opacity-50"
          >
            {isLoading ? t.search.searching : t.search.searchBtn}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.type}
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            >
              {ENTITY_TYPES.map((et) => (
                <option key={et} value={et}>
                  {et === "all"
                    ? t.search.all
                    : et === "function"
                      ? t.search.function
                      : et === "class"
                        ? t.search.class
                        : et === "module"
                          ? t.search.module
                          : et === "document"
                            ? t.search.document
                            : et}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.repo}
            <select
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            >
              <option value="all">{t.search.all}</option>
              {reposData?.repositories?.map((r) => (
                <option key={r.repository} value={r.repository}>
                  {r.repository}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.lang}
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {l === "all" ? t.search.all : l}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.topK}
            <input
              type="number"
              min={1}
              max={20}
              value={k}
              onChange={(e) => setK(Math.min(20, Number(e.target.value) || 10))}
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            {t.search.expandDepth}
            <input
              type="number"
              min={1}
              max={5}
              value={expandDepth}
              onChange={(e) => setExpandDepth(Number(e.target.value) || 2)}
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            {t.search.sortBy}
            <select
              value={sortFromUrl}
              onChange={(e) => {
                const v = e.target.value as "score" | "name" | "path";
                const params = new URLSearchParams(searchParams);
                params.set("sort", v);
                params.set("page", "1");
                setSearchParams(params);
              }}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            >
              <option value="score">{t.search.sortScore}</option>
              <option value="name">{t.search.sortName}</option>
              <option value="path">{t.search.sortPath}</option>
            </select>
          </label>
        </div>
      </form>

      {isLoading && !hybridResult && <SearchResultSkeleton count={4} />}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {(error as Error).message}
        </div>
      )}

      {hybridResult && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-gray-400 dark:text-gray-500">
              {hybridResult.total ?? 0} {t.search.resultsFor} "{hybridResult.query}"
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={pageFromUrl <= 1}
                  onClick={() => {
                    const params = new URLSearchParams(searchParams);
                    params.set("page", String(Math.max(1, pageFromUrl - 1)));
                    setSearchParams(params);
                  }}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  {t.search.pagePrev}
                </button>
                <span className="text-xs text-gray-500 dark:text-gray-400">{hybridPageIndicator}</span>
                <button
                  type="button"
                  disabled={pageFromUrl >= hybridTotalPages}
                  onClick={() => {
                    const params = new URLSearchParams(searchParams);
                    params.set("page", String(Math.min(hybridTotalPages, pageFromUrl + 1)));
                    setSearchParams(params);
                  }}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  {t.search.pageNext}
                </button>
              <button
                type="button"
                onClick={() => {
                  const blob = new Blob([JSON.stringify(hybridResult, null, 2)], {
                    type: "application/json",
                  });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `search-results-${Date.now()}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
              >
                <Download size={14} />
                {t.search.exportJson}
              </button>
            </div>
          </div>

          {hybridResult.semantic_matches?.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">{t.search.semanticMatches}</h3>
              {hybridResult.semantic_matches.map((m, i) => (
                <SearchResultCard
                  key={`s-${i}`}
                  match={m}
                  highlightQuery={hybridResult.query?.trim() ? hybridResult.query : query}
                />
              ))}
            </div>
          )}

          {hybridResult.graph_context?.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-gray-700">{t.search.graphContext}</h3>
              <GraphContextCards items={hybridResult.graph_context} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
