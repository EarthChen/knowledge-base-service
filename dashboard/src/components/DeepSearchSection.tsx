import { useState } from "react";
import { Brain, Loader2 } from "lucide-react";
import { useDeepSearch } from "../api/hooks";
import { useI18n } from "../i18n/context";
import JsonView from "./JsonView";
import MarkdownRenderer from "./wiki/MarkdownRenderer";
import DeepResearchTimeline from "./DeepResearchTimeline";
import { useDeepSearchStream } from "../hooks/useDeepSearchStream";
import { getErrorMessage } from "../utils/errorUtils";

function conclusionMarkdownText(c: Record<string, unknown> | null): string {
  if (!c) return "";
  for (const key of ["analysis", "markdown", "content", "text"] as const) {
    const v = c[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  return "";
}

type Props = {
  /** When false, hides the page-level title (e.g. embedded in unified search). */
  showTitle?: boolean;
};

export default function DeepSearchSection({ showTitle = true }: Props) {
  const [query, setQuery] = useState("");
  const [maxIterations, setMaxIterations] = useState(3);
  const [includeCode, setIncludeCode] = useState(true);
  const [traceOpen, setTraceOpen] = useState(true);
  const [streamMode, setStreamMode] = useState(true);

  const { t } = useI18n();
  const deepSearch = useDeepSearch();
  const stream = useDeepSearchStream();

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    if (streamMode) {
      void stream.start({
        query: query.trim(),
        max_iterations: maxIterations,
      });
    } else {
      deepSearch.mutate({
        query: query.trim(),
        max_iterations: maxIterations,
        include_code: includeCode,
      });
    }
  }

  const busy = streamMode ? stream.isStreaming : deepSearch.isPending;
  const submitLabel = busy
    ? t.search.deepSearching
    : t.search.searchBtn;

  function onStreamToggle(next: boolean) {
    if (!next && stream.isStreaming) stream.cancel();
    setStreamMode(next);
  }

  const streamMarkdown = conclusionMarkdownText(stream.conclusion);

  return (
    <div className="space-y-6">
      {showTitle && (
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
          <Brain size={20} className="text-amber-600 dark:text-amber-400" />
          {t.search.deepPageTitle}
        </h2>
      )}

      <form
        onSubmit={handleSearch}
        className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900"
      >
        <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">{t.search.deepPageDesc}</p>
        <div className="flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.search.deepPlaceholder}
            className="flex-1 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-amber-500 dark:focus:ring-amber-700"
          />
          <button
            type="submit"
            disabled={busy || !query.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-amber-500 disabled:opacity-50 dark:bg-amber-600 dark:hover:bg-amber-500"
          >
            {busy && <Loader2 size={16} className="animate-spin" />}
            {submitLabel}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <input
              type="checkbox"
              checked={streamMode}
              onChange={(e) => onStreamToggle(e.target.checked)}
              className="rounded border-gray-300 text-amber-600 focus:ring-amber-500 dark:border-gray-600"
            />
            {t.search.streamMode}
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            {t.search.maxIterations}
            <input
              type="number"
              min={1}
              max={5}
              value={maxIterations}
              onChange={(e) =>
                setMaxIterations(Math.min(5, Math.max(1, Number(e.target.value) || 3)))
              }
              className="w-16 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
          </label>
          <label
            className={`flex cursor-pointer items-center gap-2 text-xs text-gray-500 dark:text-gray-400 ${
              streamMode ? "opacity-50" : ""
            }`}
            title={streamMode ? t.search.includeCodeStreamHint : undefined}
          >
            <input
              type="checkbox"
              checked={includeCode}
              disabled={streamMode}
              onChange={(e) => setIncludeCode(e.target.checked)}
              className="rounded border-gray-300 text-amber-600 focus:ring-amber-500 disabled:cursor-not-allowed dark:border-gray-600"
            />
            {t.search.includeCode}
          </label>
        </div>
      </form>

      {streamMode && stream.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
          {stream.error}
        </div>
      )}

      {!streamMode && deepSearch.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
          {getErrorMessage(deepSearch.error, t.common.unexpectedError)}
        </div>
      )}

      {streamMode && (stream.stages.length > 0 || stream.isStreaming) && (
        <div className="space-y-4">
          <DeepResearchTimeline stages={stream.stages} />
          {streamMarkdown ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">{t.search.analysis}</h3>
              <div className="prose prose-sm max-w-none text-gray-600 dark:text-gray-400 dark:prose-invert">
                <MarkdownRenderer content={streamMarkdown} />
              </div>
            </div>
          ) : stream.conclusion ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">{t.search.analysis}</h3>
              <JsonView data={stream.conclusion} />
            </div>
          ) : null}
          {stream.conclusion &&
            Array.isArray((stream.conclusion as Record<string, unknown>).business_flows) &&
            ((stream.conclusion as Record<string, unknown>).business_flows as unknown[]).length > 0 && (
              <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
                <h3 className="mb-3 text-sm font-medium text-gray-700 dark:text-gray-300">
                  {t.search.businessFlows} (
                  {((stream.conclusion as Record<string, unknown>).business_flows as unknown[]).length})
                </h3>
                <div className="space-y-2">
                  {(
                    (stream.conclusion as Record<string, unknown>).business_flows as Array<
                      Record<string, unknown>
                    >
                  ).map((f, i) => (
                    <div
                      key={i}
                      className="rounded-lg border border-gray-100 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/80"
                    >
                      <span className="font-medium text-gray-800 dark:text-gray-100">
                        {String(f.flow || f.name || "")}
                      </span>
                      {f.description && (
                        <span className="ml-2 text-xs text-gray-500">{String(f.description)}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          {stream.conclusion &&
            Array.isArray((stream.conclusion as Record<string, unknown>).code_locations) &&
            ((stream.conclusion as Record<string, unknown>).code_locations as unknown[]).length > 0 && (
              <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
                <h3 className="mb-3 text-sm font-medium text-gray-700 dark:text-gray-300">
                  {t.search.codeLocations} (
                  {((stream.conclusion as Record<string, unknown>).code_locations as unknown[]).length})
                </h3>
                <div className="space-y-2">
                  {(
                    (stream.conclusion as Record<string, unknown>).code_locations as Array<
                      Record<string, unknown>
                    >
                  ).map((loc, i) => (
                    <div
                      key={i}
                      className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3 text-sm dark:border-gray-700 dark:bg-gray-800/80"
                    >
                      <code className="rounded bg-gray-200 px-1.5 py-0.5 text-xs dark:bg-gray-700">
                        {String(loc.path || "")}
                      </code>
                      {loc.context && (
                        <span className="max-w-md truncate text-xs text-gray-500">
                          {String(loc.context)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
        </div>
      )}

      {!streamMode && deepSearch.data && (
        <div className="space-y-4">
          {(deepSearch.data.error || deepSearch.data.sufficient === false) && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200">
              {t.search.llmRequired}
            </div>
          )}
          {deepSearch.data.analysis ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <h3 className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">{t.search.analysis}</h3>
              <div className="prose prose-sm max-w-none text-gray-600 dark:text-gray-400 dark:prose-invert">
                <MarkdownRenderer content={deepSearch.data.analysis} />
              </div>
            </div>
          ) : !deepSearch.data.business_flows?.length &&
            !deepSearch.data.code_locations?.length ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
              {t.search.noAnalysis}
            </div>
          ) : null}
          {deepSearch.data.business_flows && deepSearch.data.business_flows.length > 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <h3 className="mb-3 text-sm font-medium text-gray-700 dark:text-gray-300">
                {t.search.businessFlows} ({deepSearch.data.business_flows.length})
              </h3>
              <div className="space-y-2">
                {deepSearch.data.business_flows.map((f, i) => (
                  <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/80">
                    <span className="font-medium text-gray-800 dark:text-gray-100">{f.name}</span>
                    {f.impact != null && (
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{String(f.impact)}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {deepSearch.data.code_locations && deepSearch.data.code_locations.length > 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <h3 className="mb-3 text-sm font-medium text-gray-700 dark:text-gray-300">
                {t.search.codeLocations} ({deepSearch.data.code_locations.length})
              </h3>
              <div className="space-y-2">
                {deepSearch.data.code_locations.map((loc, i) => (
                  <div
                    key={i}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3 text-sm dark:border-gray-700 dark:bg-gray-800/80"
                  >
                    {loc.function != null && (
                      <code className="font-medium text-sky-700 dark:text-sky-400">{String(loc.function)}</code>
                    )}
                    {loc.file != null && (
                      <span className="text-xs text-gray-400 dark:text-gray-500">{String(loc.file)}</span>
                    )}
                    {loc.relevance != null && (
                      <span className="ml-auto text-xs text-gray-500 dark:text-gray-400">
                        {String(loc.relevance)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {deepSearch.data.search_trace && deepSearch.data.search_trace.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <button
                type="button"
                onClick={() => setTraceOpen(!traceOpen)}
                className="mb-2 flex w-full items-center justify-between text-left text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                <span>
                  {t.search.searchTrace} ({deepSearch.data.search_trace.length})
                </span>
                <span className="text-xs text-gray-400 dark:text-gray-500">{traceOpen ? "▼" : "▶"}</span>
              </button>
              <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">{t.search.searchTraceHint}</p>
              {traceOpen && <JsonView data={deepSearch.data.search_trace} />}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
