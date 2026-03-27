import { useState } from "react";
import { Search, Zap } from "lucide-react";
import { useSemanticSearch, useHybridSearch } from "../api/hooks";
import { useI18n } from "../i18n/context";
import SearchResultCard from "../components/SearchResultCard";
import JsonView from "../components/JsonView";

type SearchMode = "semantic" | "hybrid";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("semantic");
  const [entityType, setEntityType] = useState("all");
  const [k, setK] = useState(10);
  const [expandDepth, setExpandDepth] = useState(2);

  const { t } = useI18n();
  const semantic = useSemanticSearch();
  const hybrid = useHybridSearch();

  const isLoading = semantic.isPending || hybrid.isPending;

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    if (mode === "semantic") {
      semantic.mutate({ query: query.trim(), k, entity_type: entityType });
    } else {
      hybrid.mutate({ query: query.trim(), k, expand_depth: expandDepth });
    }
  }

  const semanticMatches = semantic.data?.matches ?? [];
  const hybridResult = hybrid.data;
  const error = semantic.error || hybrid.error;

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">{t.search.title}</h2>

      <form
        onSubmit={handleSearch}
        className="rounded-xl border border-gray-200 bg-white p-5"
      >
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("semantic")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              mode === "semantic"
                ? "bg-sky-100 text-sky-600"
                : "text-gray-400 hover:text-gray-700"
            }`}
          >
            <Search size={14} /> {t.search.semantic}
          </button>
          <button
            type="button"
            onClick={() => setMode("hybrid")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              mode === "hybrid"
                ? "bg-purple-100 text-purple-600"
                : "text-gray-400 hover:text-gray-700"
            }`}
          >
            <Zap size={14} /> {t.search.hybrid}
          </button>
        </div>

        <div className="mt-4 flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.search.placeholder}
            className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300"
          />
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className="rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
          >
            {isLoading ? t.search.searching : t.search.searchBtn}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          {mode === "semantic" && (
            <label className="flex items-center gap-2 text-xs text-gray-500">
              {t.search.type}
              <select
                value={entityType}
                onChange={(e) => setEntityType(e.target.value)}
                className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
              >
                <option value="all">{t.search.all}</option>
                <option value="function">{t.search.function}</option>
                <option value="class">{t.search.class}</option>
                <option value="document">{t.search.document}</option>
              </select>
            </label>
          )}
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.topK}
            <input
              type="number"
              min={1}
              max={50}
              value={k}
              onChange={(e) => setK(Number(e.target.value) || 10)}
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            />
          </label>
          {mode === "hybrid" && (
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
          )}
        </div>
      </form>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {(error as Error).message}
        </div>
      )}

      {mode === "semantic" && semanticMatches.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-gray-400">
            {semantic.data?.total ?? 0} {t.search.resultsFor} "{semantic.data?.query}"
          </p>
          {semanticMatches.map((m, i) => (
            <SearchResultCard key={i} match={m} />
          ))}
        </div>
      )}

      {mode === "hybrid" && hybridResult && (
        <div className="space-y-4">
          <p className="text-xs text-gray-400">
            {hybridResult.total ?? 0} {t.search.resultsFor} "{hybridResult.query}"
          </p>

          {hybridResult.semantic_matches?.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">{t.search.semanticMatches}</h3>
              {hybridResult.semantic_matches.map((m, i) => (
                <SearchResultCard key={`s-${i}`} match={m} />
              ))}
            </div>
          )}

          {hybridResult.graph_context?.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-gray-700">
                {t.search.graphContext}
              </h3>
              <JsonView data={hybridResult.graph_context} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
