import { useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Zap, Brain, Clock, X, Download, BookOpen } from "lucide-react";
import { useHybridSearch, useRepositories } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useSearchHistory } from "../hooks/useSearchHistory";
import SearchResultCard from "../components/SearchResultCard";
import SearchResultSkeleton from "../components/SearchResultSkeleton";
import DeepSearchSection from "../components/DeepSearchSection";
import GraphContextCards from "../components/GraphContextCards";
import RepoSelector from "../components/RepoSelector";
import WikiGlobalSearchBar from "../components/wiki/WikiGlobalSearchBar";

type SearchMode = "hybrid" | "wiki" | "deep";

const ENTITY_TYPES = ["all", "function", "class", "module", "document"] as const;
const LANGUAGES = ["all", "python", "java", "go", "javascript", "typescript"] as const;

const PAGE_SIZE = 20;

function parseSortParam(raw: string | null): "score" | "name" | "path" {
  if (raw === "name" || raw === "path" || raw === "score") return raw;
  return "score";
}

function parseModeParam(raw: string | null): SearchMode {
  if (raw === "wiki" || raw === "deep" || raw === "hybrid") return raw;
  return "hybrid";
}

/** Comma-separated in `repo` query param; empty or "all" = no repository filter. */
function parseRepoParam(raw: string | null): string[] {
  if (!raw || raw === "all") return [];
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function formatRepoParam(repos: string[]): string {
  if (repos.length === 0) return "all";
  return repos.join(",");
}

function tabClass(active: boolean, accent: "purple" | "sky" | "amber"): string {
  if (!active) {
    return "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-400 transition-colors hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300";
  }
  if (accent === "purple") {
    return "flex items-center gap-1.5 rounded-lg bg-purple-100 px-3 py-1.5 text-xs font-medium text-purple-600 dark:bg-purple-950/60 dark:text-purple-300";
  }
  if (accent === "sky") {
    return "flex items-center gap-1.5 rounded-lg bg-sky-100 px-3 py-1.5 text-xs font-medium text-sky-700 dark:bg-sky-950/60 dark:text-sky-300";
  }
  return "flex items-center gap-1.5 rounded-lg bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-700 dark:bg-amber-950/60 dark:text-amber-300";
}

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [entityType, setEntityType] = useState("all");
  const [selectedRepos, setSelectedRepos] = useState<string[]>(() =>
    parseRepoParam(searchParams.get("repo")),
  );
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

  const mode = parseModeParam(searchParams.get("mode"));
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
    const repoList = parseRepoParam(searchParams.get("repo"));
    const langParam = searchParams.get("lang") ?? "all";
    const pageParam = Math.max(1, Number.parseInt(searchParams.get("page") || "1", 10) || 1);
    const sortParam = parseSortParam(searchParams.get("sort"));
    const modeParam = parseModeParam(searchParams.get("mode"));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync URL navigation into form state
    setQuery(raw);
    setSelectedRepos(repoList);
    setLanguage(langParam);
    const q = raw.trim();
    if (!q || modeParam !== "hybrid") return;
    runHybridSearch({
      query: q,
      k,
      expand_depth: expandDepth,
      entity_type: entityType === "all" ? undefined : entityType,
      ...(repoList.length > 1
        ? { repositories: repoList }
        : repoList.length === 1
          ? { repository: repoList[0] }
          : {}),
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

  function setModeTab(next: SearchMode) {
    const params = new URLSearchParams(searchParams);
    params.set("mode", next);
    setSearchParams(params, { replace: true });
  }

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    addEntry(query.trim());
    setShowHistory(false);
    const params = new URLSearchParams(searchParams);
    params.set("q", query.trim());
    params.set("repo", formatRepoParam(selectedRepos));
    params.set("lang", language);
    params.set("page", "1");
    params.set("sort", parseSortParam(searchParams.get("sort")));
    params.set("mode", "hybrid");
    setSearchParams(params);
  }

  useEffect(() => {
    if (mode !== "wiki") return;
    const params = new URLSearchParams(searchParams);
    const repoStr = formatRepoParam(selectedRepos);
    if (params.get("repo") === repoStr) return;
    params.set("repo", repoStr);
    setSearchParams(params, { replace: true });
  }, [mode, selectedRepos, searchParams, setSearchParams]);

  const applyHistoryQuery = useCallback(
    (h: string) => {
      setQuery(h);
      setShowHistory(false);
      setHighlightedHistoryIndex(-1);
      addEntry(h);
      const params = new URLSearchParams(searchParams);
      params.set("q", h);
      params.set("repo", formatRepoParam(selectedRepos));
      params.set("lang", language);
      params.set("page", "1");
      params.set("sort", parseSortParam(searchParams.get("sort")));
      params.set("mode", "hybrid");
      setSearchParams(params);
    },
    [addEntry, selectedRepos, language, searchParams, setSearchParams],
  );

  const handleHistoryKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
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

  const repoOptions = reposData?.repositories?.map((r) => r.repository) ?? [];

  const onWikiLinkedSearch = useCallback(
    (wikiQuery: string) => {
      const params = new URLSearchParams(searchParams);
      params.set("q", wikiQuery);
      params.set("mode", "wiki");
      params.set("repo", formatRepoParam(selectedRepos));
      params.delete("page");
      setSearchParams(params);
    },
    [searchParams, selectedRepos, setSearchParams],
  );

  const tabRow = (
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={() => setModeTab("hybrid")} className={tabClass(mode === "hybrid", "purple")}>
        <Zap size={14} /> {t.search.hybrid}
      </button>
      <button type="button" onClick={() => setModeTab("wiki")} className={tabClass(mode === "wiki", "sky")}>
        <BookOpen size={14} /> {t.search.wiki}
      </button>
      <button type="button" onClick={() => setModeTab("deep")} className={tabClass(mode === "deep", "amber")}>
        <Brain size={14} /> {t.search.deepResearch}
      </button>
    </div>
  );

  if (mode === "deep") {
    return (
      <div className="space-y-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t.search.title}</h2>
        {tabRow}
        <DeepSearchSection showTitle={false} />
      </div>
    );
  }

  if (mode === "wiki") {
    return (
      <div className="space-y-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t.search.title}</h2>
        {tabRow}

        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
          <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">{t.wiki.globalSearchDescription}</p>
          <div className="mb-4 max-w-xl">
            <span className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">{t.search.repo}</span>
            <RepoSelector
              options={repoOptions}
              selected={selectedRepos}
              onChange={setSelectedRepos}
              groupLabel={t.search.repo}
              labels={{
                allRepos: t.search.repoSelectorAllRepos,
                addRepo: t.search.repoSelectorAdd,
                filterPlaceholder: t.search.repoSelectorFilterPlaceholder,
                selectedCount: t.search.repoSelectorSelectedCount,
                removeRepo: t.search.repoSelectorRemoveRepo,
                noMatches: t.search.repoSelectorNoMatches,
              }}
            />
          </div>
          <WikiGlobalSearchBar
            linkedQuery={searchParams.get("q") ?? ""}
            onLinkedSearch={onWikiLinkedSearch}
            repositories={selectedRepos.length > 0 ? selectedRepos : null}
            showIntro={false}
            className="border-0 bg-transparent p-0 shadow-none dark:bg-transparent"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t.search.title}</h2>

      <form onSubmit={handleSearch} className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
        {tabRow}

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
              className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-purple-500 dark:focus:ring-purple-600"
            />
            {showHistory && history.length > 0 && (
              <div
                id={historyListId}
                role="listbox"
                aria-label={t.search.title}
                className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-800 dark:shadow-gray-900/50"
              >
                {history.slice(0, 10).map((h, i) => (
                  <div
                    key={h}
                    id={`${historyListId}-opt-${i}`}
                    role="option"
                    aria-selected={highlightedHistoryIndex === i}
                    className={`flex cursor-pointer items-center gap-2 px-4 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700/80 ${
                      highlightedHistoryIndex === i ? "bg-purple-50 dark:bg-purple-950/50" : ""
                    }`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      applyHistoryQuery(h);
                    }}
                    onMouseEnter={() => setHighlightedHistoryIndex(i)}
                  >
                    <Clock size={12} className="shrink-0 text-gray-400 dark:text-gray-500" />
                    <span className="flex-1 truncate text-gray-700 dark:text-gray-300">{h}</span>
                    <button
                      type="button"
                      className="shrink-0 rounded p-0.5 text-gray-300 hover:text-gray-500 dark:text-gray-500 dark:hover:text-gray-300"
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

        <div className="mt-3 flex flex-wrap items-start gap-4">
          <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            {t.search.type}
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
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
          <div className="flex min-w-[12rem] max-w-full flex-col gap-1 text-xs text-gray-500 dark:text-gray-400">
            <span className="shrink-0 font-medium text-gray-600 dark:text-gray-400">{t.search.repo}</span>
            <RepoSelector
              options={repoOptions}
              selected={selectedRepos}
              onChange={setSelectedRepos}
              groupLabel={t.search.repo}
              labels={{
                allRepos: t.search.repoSelectorAllRepos,
                addRepo: t.search.repoSelectorAdd,
                filterPlaceholder: t.search.repoSelectorFilterPlaceholder,
                selectedCount: t.search.repoSelectorSelectedCount,
                removeRepo: t.search.repoSelectorRemoveRepo,
                noMatches: t.search.repoSelectorNoMatches,
              }}
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            {t.search.lang}
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {l === "all" ? t.search.all : l}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            {t.search.topK}
            <input
              type="number"
              min={1}
              max={20}
              value={k}
              onChange={(e) => setK(Math.min(20, Number(e.target.value) || 10))}
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
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
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
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
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">{t.search.semanticMatches}</h3>
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
              <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">{t.search.graphContext}</h3>
              <GraphContextCards items={hybridResult.graph_context} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
