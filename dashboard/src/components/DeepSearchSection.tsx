import { useState } from "react";
import { Brain, Loader2 } from "lucide-react";
import { useDeepSearch } from "../api/hooks";
import { useI18n } from "../i18n/context";
import JsonView from "./JsonView";
import MarkdownRenderer from "./MarkdownRenderer";

type Props = {
  /** When false, hides the page-level title (e.g. embedded in unified search). */
  showTitle?: boolean;
};

export default function DeepSearchSection({ showTitle = true }: Props) {
  const [query, setQuery] = useState("");
  const [maxIterations, setMaxIterations] = useState(3);
  const [includeCode, setIncludeCode] = useState(true);
  const [traceOpen, setTraceOpen] = useState(true);

  const { t } = useI18n();
  const deepSearch = useDeepSearch();

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    deepSearch.mutate({
      query: query.trim(),
      max_iterations: maxIterations,
      include_code: includeCode,
    });
  }

  const submitLabel = deepSearch.isPending
    ? t.search.deepSearching
    : t.search.searchBtn;

  return (
    <div className="space-y-6">
      {showTitle && (
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <Brain size={20} className="text-amber-600" />
          {t.search.deepPageTitle}
        </h2>
      )}

      <form
        onSubmit={handleSearch}
        className="rounded-xl border border-gray-200 bg-white p-5"
      >
        <p className="mb-3 text-xs text-gray-500">{t.search.deepPageDesc}</p>
        <div className="flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.search.deepPlaceholder}
            className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-300"
          />
          <button
            type="submit"
            disabled={deepSearch.isPending || !query.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-amber-500 disabled:opacity-50"
          >
            {deepSearch.isPending && <Loader2 size={16} className="animate-spin" />}
            {submitLabel}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-gray-500">
            {t.search.maxIterations}
            <input
              type="number"
              min={1}
              max={5}
              value={maxIterations}
              onChange={(e) =>
                setMaxIterations(Math.min(5, Math.max(1, Number(e.target.value) || 3)))
              }
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none"
            />
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={includeCode}
              onChange={(e) => setIncludeCode(e.target.checked)}
              className="rounded border-gray-300 text-amber-600 focus:ring-amber-500"
            />
            {t.search.includeCode}
          </label>
        </div>
      </form>

      {deepSearch.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
          {(deepSearch.error as Error).message}
        </div>
      )}

      {deepSearch.data && (
        <div className="space-y-4">
          {(deepSearch.data.error || deepSearch.data.sufficient === false) && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              {t.search.llmRequired}
            </div>
          )}
          {deepSearch.data.analysis ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h3 className="mb-2 text-sm font-medium text-gray-700">{t.search.analysis}</h3>
              <div className="prose prose-sm max-w-none text-gray-600">
                <MarkdownRenderer content={deepSearch.data.analysis} />
              </div>
            </div>
          ) : !deepSearch.data.business_flows?.length &&
            !deepSearch.data.code_locations?.length ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 text-sm text-gray-500">
              {t.search.noAnalysis}
            </div>
          ) : null}
          {deepSearch.data.business_flows && deepSearch.data.business_flows.length > 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h3 className="mb-3 text-sm font-medium text-gray-700">
                {t.search.businessFlows} ({deepSearch.data.business_flows.length})
              </h3>
              <div className="space-y-2">
                {deepSearch.data.business_flows.map((f, i) => (
                  <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <span className="font-medium text-gray-800">{f.name}</span>
                    {f.impact != null && (
                      <p className="mt-1 text-xs text-gray-500">{String(f.impact)}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {deepSearch.data.code_locations && deepSearch.data.code_locations.length > 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h3 className="mb-3 text-sm font-medium text-gray-700">
                {t.search.codeLocations} ({deepSearch.data.code_locations.length})
              </h3>
              <div className="space-y-2">
                {deepSearch.data.code_locations.map((loc, i) => (
                  <div
                    key={i}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3 text-sm"
                  >
                    {loc.function != null && (
                      <code className="font-medium text-sky-700">{String(loc.function)}</code>
                    )}
                    {loc.file != null && (
                      <span className="text-xs text-gray-400">{String(loc.file)}</span>
                    )}
                    {loc.relevance != null && (
                      <span className="ml-auto text-xs text-gray-500">
                        {String(loc.relevance)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {deepSearch.data.search_trace && deepSearch.data.search_trace.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <button
                type="button"
                onClick={() => setTraceOpen(!traceOpen)}
                className="mb-2 flex w-full items-center justify-between text-left text-sm font-medium text-gray-700"
              >
                <span>
                  {t.search.searchTrace} ({deepSearch.data.search_trace.length})
                </span>
                <span className="text-xs text-gray-400">{traceOpen ? "▼" : "▶"}</span>
              </button>
              <p className="mb-3 text-xs text-gray-500">{t.search.searchTraceHint}</p>
              {traceOpen && <JsonView data={deepSearch.data.search_trace} />}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
