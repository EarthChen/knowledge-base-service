import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2, MessageCircle, Send } from "lucide-react";
import { Link } from "react-router-dom";
import { useWikiAsk } from "../../hooks/useWikiAsk";
import type { WikiAskSource } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";
import { buildIdeHref, type EditorId } from "./editorLinks";
import { EDITOR_PREF_KEY } from "./SourceLink";

function readEditorPref(): EditorId {
  try {
    const v = localStorage.getItem(EDITOR_PREF_KEY);
    if (v === "vscode" || v === "cursor" || v === "idea") return v;
  } catch {
    /* ignore */
  }
  return "cursor";
}

function wikiHref(repository: string, path: string): string {
  const er = encodeURIComponent(repository);
  const ep = path
    .split("/")
    .filter(Boolean)
    .map((s) => encodeURIComponent(s))
    .join("/");
  return `/wiki/${er}/${ep}`;
}

function SourceRef({
  repository,
  s,
}: {
  repository: string;
  s: WikiAskSource;
}) {
  const editor = readEditorPref();
  const ide =
    s.file_path && s.start_line > 0
      ? buildIdeHref(editor, repository, s.file_path, s.start_line)
      : null;
  return (
    <li className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-sm">
      <div className="font-medium text-gray-900">{s.entity}</div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600">
        {s.wiki_page && (
          <Link
            to={wikiHref(repository, s.wiki_page)}
            className="text-sky-700 underline decoration-sky-200"
          >
            {s.wiki_page}
          </Link>
        )}
        {ide && s.file_path && (
          <a href={ide} className="font-mono text-sky-700 underline decoration-sky-200">
            {s.file_path}:{s.start_line}
          </a>
        )}
        <span className="text-gray-400">score {s.relevance_score.toFixed(3)}</span>
      </div>
    </li>
  );
}

type Props = {
  repository: string | undefined;
};

export default function AskPanel({ repository }: Props) {
  const { locale } = useI18n();
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const [input, setInput] = useState("");
  const { answer, sources, isStreaming, error, ask, cancel, reset, conversationId } =
    useWikiAsk(repository);

  if (!repository?.trim()) return null;

  return (
    <section className="rounded-xl border border-gray-200 bg-gradient-to-b from-white to-gray-50/80 shadow-sm">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-semibold text-gray-900"
      >
        <span className="inline-flex items-center gap-2">
          <MessageCircle size={18} className="text-sky-600" aria-hidden />
          Ask wiki
          {conversationId && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-normal text-gray-500">
              thread
            </span>
          )}
        </span>
        {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>

      {open && (
        <div className="space-y-4 border-t border-gray-100 px-4 pb-4 pt-2">
          <p className="text-xs text-gray-500">
            Answers use hybrid search context and stream from the wiki Q&A endpoint (
            <code className="rounded bg-gray-100 px-1">POST /api/v1/wiki/ask</code>
            ).
          </p>

          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const q = input.trim();
              if (!q || isStreaming) return;
              void ask({ question: q });
              setInput("");
            }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={2}
              placeholder="Ask a question about this repository…"
              className="min-h-[44px] flex-1 resize-y rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2"
            />
            <div className="flex shrink-0 flex-col gap-2">
              <button
                type="submit"
                disabled={isStreaming || !input.trim()}
                className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
              >
                {isStreaming ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Send className="size-4" />
                )}
              </button>
              <button
                type="button"
                onClick={() => cancel()}
                disabled={!isStreaming}
                className="text-xs text-gray-600 hover:text-gray-900 disabled:opacity-40"
              >
                Stop
              </button>
              <button
                type="button"
                onClick={() => {
                  reset();
                  setInput("");
                }}
                className="text-xs text-gray-600 hover:text-gray-900"
              >
                Clear
              </button>
            </div>
          </form>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          {(answer || isStreaming) && (
            <div className="rounded-lg border border-gray-100 bg-white px-4 py-3 shadow-inner">
              <div className="prose prose-sm prose-slate max-w-none whitespace-pre-wrap">
                {answer}
                {isStreaming && (
                  <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-sky-500 align-middle" />
                )}
              </div>
            </div>
          )}

          {sources.length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                Sources
              </h4>
              <ul className="space-y-2">
                {sources.map((s, i) => (
                  <SourceRef key={`${s.wiki_page}-${s.entity}-${i}`} repository={repository} s={s} />
                ))}
              </ul>
              <p className="mt-2 text-xs text-gray-400">
                {isZh
                  ? "Ask v2: 上下文由图增强搜索提供，包含调用链和模块上下文"
                  : "Ask v2: Context enhanced by graph search including call chains and module context"}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
