import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Zap, Brain, Clock, X } from "lucide-react";
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

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [entityType, setEntityType] = useState("all");
  const [repository, setRepository] = useState("all");
  const [language, setLanguage] = useState("all");
  const [k, setK] = useState(10);
  const [expandDepth, setExpandDepth] = useState(2);

  const { data: reposData } = useRepositories();
  const { history, addEntry, removeEntry } = useSearchHistory();
  const [showHistory, setShowHistory] = useState(false);

  const { t } = useI18n();
  const { mutate: runHybridSearch, isPending: hybridPending, data: hybridResult, error } =
    useHybridSearch();

  useEffect(() => {
    const raw = searchParams.get("q") ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync ?q= from navigation into the form field
    setQuery(raw);
    const q = raw.trim();
    if (!q) return;
    runHybridSearch({
      query: q,
      k,
      expand_depth: expandDepth,
      entity_type: entityType === "all" ? undefined : entityType,
      repository: repository === "all" ? undefined : repository,
      language: language === "all" ? undefined : language,
    });
  }, [searchParams, k, expandDepth, entityType, repository, language, runHybridSearch]);

  const isLoading = hybridPending;

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    addEntry(query.trim());
    setShowHistory(false);
    runHybridSearch({
      query: query.trim(),
      k,
      expand_depth: expandDepth,
      entity_type: entityType === "all" ? undefined : entityType,
      repository: repository === "all" ? undefined : repository,
      language: language === "all" ? undefined : language,
    });
  }

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
              placeholder={t.search.placeholder}
              className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-300"
            />
            {showHistory && history.length > 0 && (
              <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                {history.slice(0, 10).map((h) => (
                  <div
                    key={h}
                    className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-gray-50 cursor-pointer"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setQuery(h);
                      setShowHistory(false);
                    }}
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
            Repo
            <select
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            >
              <option value="all">All</option>
              {reposData?.repositories?.map((r) => (
                <option key={r.repository} value={r.repository}>
                  {r.repository}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            Lang
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {l === "all" ? "All" : l}
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
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.expandDepth}
            <input
              type="number"
              min={1}
              max={5}
              value={expandDepth}
              onChange={(e) => setExpandDepth(Number(e.target.value) || 2)}
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            />
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
          <p className="text-xs text-gray-400">
            {hybridResult.total ?? 0} {t.search.resultsFor} "{hybridResult.query}"
          </p>

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
