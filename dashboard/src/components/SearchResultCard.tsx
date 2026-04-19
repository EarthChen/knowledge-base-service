import { useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Code, Copy, Check } from "lucide-react";
import type { SearchMatch } from "../api/types";
import HighlightText from "./HighlightText";
import CodeBlock from "./CodeBlock";
import { useCodeSnippet } from "../api/hooks";
import { useI18n } from "../i18n/context";

const TYPE_COLORS: Record<string, string> = {
  function:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/80 dark:text-emerald-300",
  class: "bg-sky-50 text-sky-700 dark:bg-sky-950/80 dark:text-sky-300",
  document:
    "bg-amber-50 text-amber-700 dark:bg-amber-950/80 dark:text-amber-300",
  module:
    "bg-purple-50 text-purple-700 dark:bg-purple-950/80 dark:text-purple-300",
};

export default function SearchResultCard({
  match,
  highlightQuery,
}: {
  match: SearchMatch;
  highlightQuery?: string;
}) {
  const { t } = useI18n();
  const typeStyle =
    TYPE_COLORS[match.type?.toLowerCase()] ||
    "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";

  const [showCode, setShowCode] = useState(false);
  const [copied, setCopied] = useState(false);
  const [filePathCopied, setFilePathCopied] = useState(false);
  const snippetQuery = useCodeSnippet(showCode ? (match.uid ?? null) : null);

  const wikiQuery = encodeURIComponent(match.name || "");
  const wikiHref = wikiQuery ? `/wiki?q=${wikiQuery}` : "/wiki";

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard denied in non-secure context */ }
  };

  const handleCopyFilePath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setFilePathCopied(true);
      setTimeout(() => setFilePathCopied(false), 2000);
    } catch { /* clipboard denied in non-secure context */ }
  };

  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 transition-all hover:border-gray-300 hover:shadow-sm dark:border-gray-700 dark:bg-gray-900 dark:hover:border-gray-600">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className={`inline-flex rounded-md px-2 py-0.5 text-xs font-medium ${typeStyle}`}>
          {match.type || "unknown"}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {match.uid && (
            <button
              type="button"
              onClick={() => setShowCode(!showCode)}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              <Code size={12} />
              {showCode ? t.search.hideCode ?? "Hide" : t.search.viewCode ?? "Code"}
            </button>
          )}
          <Link
            to={wikiHref}
            className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-sky-600 transition-colors hover:bg-sky-50 hover:text-sky-800 dark:text-sky-400 dark:hover:bg-sky-950 dark:hover:text-sky-200"
          >
            <BookOpen size={12} />
            {t.search.viewWiki}
          </Link>
          <span className="text-xs text-sky-600 dark:text-sky-400">
            {t.search.score}: {typeof match.score === "number" ? match.score.toFixed(4) : "—"}
          </span>
        </div>
      </div>

      <h3 className="mt-2 text-base font-semibold">
        {wikiQuery ? (
          <Link
            to={wikiHref}
            className="text-gray-900 underline decoration-transparent decoration-1 underline-offset-2 transition-colors hover:cursor-pointer hover:text-sky-800 hover:decoration-sky-600/50 dark:text-gray-100 dark:hover:text-sky-300"
          >
            {highlightQuery?.trim() ? (
              <HighlightText text={match.name || "—"} query={highlightQuery} />
            ) : (
              match.name || "—"
            )}
          </Link>
        ) : (
          <span className="text-gray-900 dark:text-gray-100">
            {highlightQuery?.trim() ? (
              <HighlightText text={match.name || "—"} query={highlightQuery} />
            ) : (
              match.name || "—"
            )}
          </span>
        )}
      </h3>

      {match.fqn && (
        <p className="mt-0.5 truncate font-mono text-xs text-sky-600/60">{match.fqn}</p>
      )}

      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        <span className="text-gray-400 dark:text-gray-500">{t.search.file}</span>{" "}
        {match.file ? (
          <button
            type="button"
            onClick={() => handleCopyFilePath(match.file)}
            className="max-w-full truncate text-left font-mono text-xs text-gray-700 underline decoration-transparent decoration-1 underline-offset-2 transition-colors hover:cursor-pointer hover:text-sky-800 hover:decoration-sky-600/40 dark:text-gray-300 dark:hover:text-sky-300"
            title={t.search.copyFilePath}
          >
            {filePathCopied ? (
              <span className="inline-flex items-center gap-1 text-green-600">
                <Check size={12} aria-hidden />
                {match.file}
              </span>
            ) : (
              match.file
            )}
          </button>
        ) : (
          "—"
        )}
        {match.line != null && (
          <>
            {" "}
            <span className="text-gray-400 dark:text-gray-500">·</span> {t.search.line}{" "}
            {match.line}
          </>
        )}
      </p>

      {match.signature && (
        <p className="mt-2 truncate font-mono text-xs text-gray-400 dark:text-gray-500">
          {match.signature}
        </p>
      )}

      {(match.docstring || match.content) && (
        <p className="mt-2 line-clamp-3 text-sm text-gray-500 dark:text-gray-400">
          <HighlightText
            text={match.docstring || match.content || ""}
            query={highlightQuery ?? ""}
          />
        </p>
      )}

      {showCode && (
        <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-600 dark:bg-gray-800/80">
          {snippetQuery.isLoading && (
            <p className="text-xs text-gray-400 dark:text-gray-500">Loading code…</p>
          )}
          {snippetQuery.error && (
            <p className="text-xs text-red-600 dark:text-red-400">{snippetQuery.error.message}</p>
          )}
          {snippetQuery.data && (
            <div>
              <div className="mb-2 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
                <span>
                  L{snippetQuery.data.start_line}–{snippetQuery.data.end_line}
                  {snippetQuery.data.fqn && (
                    <span className="ml-2 text-sky-600/60">{snippetQuery.data.fqn}</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => handleCopy(snippetQuery.data!.code_snippet)}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
                >
                  {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <CodeBlock
                code={snippetQuery.data.code_snippet || "(no code stored)"}
                filePath={snippetQuery.data.file ?? match.file}
                startLine={snippetQuery.data.start_line}
              />
            </div>
          )}
        </div>
      )}
    </article>
  );
}
