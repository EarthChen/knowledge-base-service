import { useState } from "react";
import { Link } from "react-router-dom";
import { Search, Zap, Brain, Building2 } from "lucide-react";
import {
  useSemanticSearch,
  useHybridSearch,
  useBusinessSearch,
} from "../api/hooks";
import { useI18n } from "../i18n/context";
import SearchResultCard from "../components/SearchResultCard";
import JsonView from "../components/JsonView";
import DeepSearchSection from "../components/DeepSearchSection";

type SearchMode = "semantic" | "hybrid" | "deep" | "business";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("semantic");
  const [entityType, setEntityType] = useState("all");
  const [k, setK] = useState(10);
  const [expandDepth, setExpandDepth] = useState(2);
  const [includeCode, setIncludeCode] = useState(true);
  const [businessSearchType, setBusinessSearchType] = useState("all");

  const { t } = useI18n();
  const semantic = useSemanticSearch();
  const hybrid = useHybridSearch();
  const businessSearch = useBusinessSearch();

  const isLoading = semantic.isPending || hybrid.isPending || businessSearch.isPending;

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    if (mode === "semantic") {
      semantic.mutate({ query: query.trim(), k, entity_type: entityType });
    } else if (mode === "hybrid") {
      hybrid.mutate({ query: query.trim(), k, expand_depth: expandDepth });
    } else {
      businessSearch.mutate({
        query: query.trim(),
        search_type: businessSearchType,
        k,
        include_code: includeCode,
      });
    }
  }

  const semanticMatches = semantic.data?.matches ?? [];
  const hybridResult = hybrid.data;
  const error = semantic.error || hybrid.error || businessSearch.error;

  const placeholder =
    mode === "business" ? t.search.businessPlaceholder : t.search.placeholder;

  const submitLabel = isLoading ? t.search.searching : t.search.searchBtn;

  const submitClass =
    mode === "semantic"
      ? "rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
      : mode === "hybrid"
        ? "rounded-lg bg-purple-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-purple-500 disabled:opacity-50"
        : "rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50";

  if (mode === "deep") {
    return (
      <div className="space-y-6">
        <h2 className="text-lg font-semibold text-gray-900">{t.search.title}</h2>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setMode("semantic")}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-400 transition-colors hover:text-gray-700"
          >
            <Search size={14} /> {t.search.semantic}
          </button>
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
          <button
            type="button"
            onClick={() => setMode("business")}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-400 transition-colors hover:text-gray-700"
          >
            <Building2 size={14} /> {t.search.business}
          </button>
        </div>

        <p className="text-xs text-gray-500">
          {t.search.deepPageDesc}{" "}
          <Link to="/deep-search" className="text-amber-700 underline hover:text-amber-800">
            {t.nav.deepSearch}
          </Link>
        </p>

        <DeepSearchSection showTitle={false} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">{t.search.title}</h2>

      <form
        onSubmit={handleSearch}
        className="rounded-xl border border-gray-200 bg-white p-5"
      >
        <div className="flex flex-wrap gap-2">
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
          <button
            type="button"
            onClick={() => setMode("deep")}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-400 transition-colors hover:text-gray-700"
          >
            <Brain size={14} /> {t.search.deep}
          </button>
          <button
            type="button"
            onClick={() => setMode("business")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              mode === "business"
                ? "bg-emerald-100 text-emerald-700"
                : "text-gray-400 hover:text-gray-700"
            }`}
          >
            <Building2 size={14} /> {t.search.business}
          </button>
        </div>

        <div className="mt-4 flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300"
          />
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className={submitClass}
          >
            {submitLabel}
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
          {(mode === "semantic" || mode === "hybrid" || mode === "business") && (
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
          )}
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
          {mode === "business" && (
            <label className="flex items-center gap-2 text-xs text-gray-500">
              {t.search.searchType}
              <select
                value={businessSearchType}
                onChange={(e) => setBusinessSearchType(e.target.value)}
                className="rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
              >
                <option value="all">{t.search.all}</option>
                <option value="flow">{t.search.flow}</option>
                <option value="concept">{t.search.concept}</option>
              </select>
            </label>
          )}
          {mode === "business" && (
            <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-500">
              <input
                type="checkbox"
                checked={includeCode}
                onChange={(e) => setIncludeCode(e.target.checked)}
                className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
              />
              {t.search.includeCode}
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

      {mode === "business" && businessSearch.data && (
        <div className="space-y-4">
          {(businessSearch.data.flows?.length ?? 0) > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">
                {t.search.flowResults} ({businessSearch.data.flows!.length})
              </h3>
              {businessSearch.data.flows!.map((f, i) => (
                <div key={i} className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="font-medium text-gray-900">{f.name}</h4>
                    <div className="flex shrink-0 flex-wrap justify-end gap-2">
                      {f.category && (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-600">
                          {f.category}
                        </span>
                      )}
                      {f.confidence_score != null && (
                        <span className="text-xs text-gray-400">
                          {t.search.confidence}: {(f.confidence_score * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </div>
                  <p className="mt-1 text-sm text-gray-600">{f.description}</p>
                  {f.code_locations?.length ? (
                    <div className="mt-3 space-y-1">
                      {f.code_locations.map((loc, j) => (
                        <div key={j} className="flex items-center gap-2 text-xs">
                          <code className="font-mono text-sky-600">{loc.name}</code>
                          <span className="text-gray-400">{loc.file}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          {(businessSearch.data.concepts?.length ?? 0) > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">
                {t.search.conceptResults} ({businessSearch.data.concepts!.length})
              </h3>
              {businessSearch.data.concepts!.map((c, i) => (
                <div key={i} className="rounded-xl border border-gray-200 bg-white p-4">
                  <h4 className="font-medium text-gray-900">{c.name}</h4>
                  <p className="mt-1 text-sm text-gray-600">{c.description}</p>
                  {c.aliases?.length ? (
                    <p className="mt-1 text-xs text-gray-400">
                      {t.search.aliases}: {c.aliases.join(", ")}
                    </p>
                  ) : null}
                  {c.category && (
                    <span className="mt-2 inline-block rounded-full bg-purple-50 px-2 py-0.5 text-xs text-purple-600">
                      {c.category}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
