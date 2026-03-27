import { useState } from "react";
import { Code, Copy, Check } from "lucide-react";
import type { SearchMatch } from "../api/types";
import { useCodeSnippet } from "../api/hooks";
import { useI18n } from "../i18n/context";

const TYPE_COLORS: Record<string, string> = {
  function: "bg-emerald-50 text-emerald-700",
  class: "bg-sky-50 text-sky-700",
  document: "bg-amber-50 text-amber-700",
  module: "bg-purple-50 text-purple-700",
};

export default function SearchResultCard({ match }: { match: SearchMatch }) {
  const { t } = useI18n();
  const typeStyle = TYPE_COLORS[match.type?.toLowerCase()] || "bg-gray-100 text-gray-700";

  const [showCode, setShowCode] = useState(false);
  const [copied, setCopied] = useState(false);
  const snippetQuery = useCodeSnippet(showCode ? (match.uid ?? null) : null);

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 transition-colors hover:border-gray-300">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${typeStyle}`}>
          {match.type || "unknown"}
        </span>
        <div className="flex items-center gap-2">
          {match.uid && (
            <button
              onClick={() => setShowCode(!showCode)}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900"
            >
              <Code size={12} />
              {showCode ? t.search.hideCode ?? "Hide" : t.search.viewCode ?? "Code"}
            </button>
          )}
          <span className="text-xs text-sky-600">
            {t.search.score}: {typeof match.score === "number" ? match.score.toFixed(4) : "—"}
          </span>
        </div>
      </div>

      <h3 className="mt-2 text-base font-semibold text-gray-900">{match.name || "—"}</h3>

      {match.fqn && (
        <p className="mt-0.5 truncate font-mono text-xs text-sky-600/60">{match.fqn}</p>
      )}

      <p className="mt-1 text-sm text-gray-500">
        <span className="text-gray-400">{t.search.file}</span> {match.file || "—"}
        {match.line != null && (
          <>
            {" "}
            <span className="text-gray-400">·</span> {t.search.line} {match.line}
          </>
        )}
      </p>

      {match.signature && (
        <p className="mt-2 truncate font-mono text-xs text-gray-400">
          {match.signature}
        </p>
      )}

      {(match.docstring || match.content) && (
        <p className="mt-2 line-clamp-3 text-sm text-gray-500">
          {match.docstring || match.content}
        </p>
      )}

      {showCode && (
        <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
          {snippetQuery.isLoading && (
            <p className="text-xs text-gray-400">Loading code…</p>
          )}
          {snippetQuery.error && (
            <p className="text-xs text-red-600">{snippetQuery.error.message}</p>
          )}
          {snippetQuery.data && (
            <div>
              <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
                <span>
                  L{snippetQuery.data.start_line}–{snippetQuery.data.end_line}
                  {snippetQuery.data.fqn && (
                    <span className="ml-2 text-sky-600/60">{snippetQuery.data.fqn}</span>
                  )}
                </span>
                <button
                  onClick={() => handleCopy(snippetQuery.data!.code_snippet)}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-gray-100"
                >
                  {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <pre className="max-h-80 overflow-auto text-xs leading-5 text-gray-700">
                <code>{snippetQuery.data.code_snippet || "(no code stored)"}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
