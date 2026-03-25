import { useState } from "react";
import { Code, Copy, Check } from "lucide-react";
import type { SearchMatch } from "../api/types";
import { useCodeSnippet } from "../api/hooks";
import { useI18n } from "../i18n/context";

const TYPE_COLORS: Record<string, string> = {
  function: "bg-emerald-500/15 text-emerald-400",
  class: "bg-sky-500/15 text-sky-400",
  document: "bg-amber-500/15 text-amber-400",
  module: "bg-purple-500/15 text-purple-400",
};

export default function SearchResultCard({ match }: { match: SearchMatch }) {
  const { t } = useI18n();
  const typeStyle = TYPE_COLORS[match.type?.toLowerCase()] || "bg-slate-700 text-slate-300";

  const [showCode, setShowCode] = useState(false);
  const [copied, setCopied] = useState(false);
  const snippetQuery = useCodeSnippet(showCode ? (match.uid ?? null) : null);

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <article className="rounded-xl border border-slate-800 bg-slate-850 p-4 transition-colors hover:border-slate-700">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${typeStyle}`}>
          {match.type || "unknown"}
        </span>
        <div className="flex items-center gap-2">
          {match.uid && (
            <button
              onClick={() => setShowCode(!showCode)}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-slate-400 transition-colors hover:bg-slate-700 hover:text-white"
            >
              <Code size={12} />
              {showCode ? t.search.hideCode ?? "Hide" : t.search.viewCode ?? "Code"}
            </button>
          )}
          <span className="text-xs text-sky-400/80">
            {t.search.score}: {typeof match.score === "number" ? match.score.toFixed(4) : "—"}
          </span>
        </div>
      </div>

      <h3 className="mt-2 text-base font-semibold text-white">{match.name || "—"}</h3>

      {match.fqn && (
        <p className="mt-0.5 truncate font-mono text-xs text-sky-300/60">{match.fqn}</p>
      )}

      <p className="mt-1 text-sm text-slate-400">
        <span className="text-slate-500">{t.search.file}</span> {match.file || "—"}
        {match.line != null && (
          <>
            {" "}
            <span className="text-slate-600">·</span> {t.search.line} {match.line}
          </>
        )}
      </p>

      {match.signature && (
        <p className="mt-2 truncate font-mono text-xs text-slate-500">
          {match.signature}
        </p>
      )}

      {(match.docstring || match.content) && (
        <p className="mt-2 line-clamp-3 text-sm text-slate-400">
          {match.docstring || match.content}
        </p>
      )}

      {showCode && (
        <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900 p-3">
          {snippetQuery.isLoading && (
            <p className="text-xs text-slate-500">Loading code…</p>
          )}
          {snippetQuery.error && (
            <p className="text-xs text-red-400">{snippetQuery.error.message}</p>
          )}
          {snippetQuery.data && (
            <div>
              <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                <span>
                  L{snippetQuery.data.start_line}–{snippetQuery.data.end_line}
                  {snippetQuery.data.fqn && (
                    <span className="ml-2 text-sky-400/60">{snippetQuery.data.fqn}</span>
                  )}
                </span>
                <button
                  onClick={() => handleCopy(snippetQuery.data!.code_snippet)}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-slate-800"
                >
                  {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <pre className="max-h-80 overflow-auto text-xs leading-5 text-slate-300">
                <code>{snippetQuery.data.code_snippet || "(no code stored)"}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
