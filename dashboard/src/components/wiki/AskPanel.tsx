import { useEffect, useRef, useState } from "react";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  History,
  Loader2,
  MessageCircle,
  Send,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useWikiAsk } from "../../hooks/useWikiAsk";
import { useConversationHistory } from "../../hooks/useConversationHistory";
import type { WikiConversationMessage } from "../../hooks/useConversationHistory";
import type { WikiAskSource } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";
import { buildIdeHref, type EditorId } from "./editorLinks";
import { EDITOR_PREF_KEY } from "./SourceLink";
import DeepResearchTimeline from "../DeepResearchTimeline";
import { useDeepSearchStream } from "../../hooks/useDeepSearchStream";
import MarkdownRenderer from "../MarkdownRenderer";

function readEditorPref(): EditorId {
  try {
    const v = localStorage.getItem(EDITOR_PREF_KEY);
    if (v === "vscode" || v === "cursor" || v === "idea") return v;
  } catch {
    /* ignore */
  }
  return "cursor";
}

function assistantTextFromMessages(messages: WikiConversationMessage[]): string {
  const parts = messages
    .filter((m) => m.role === "assistant")
    .map((m) => m.content.trim())
    .filter(Boolean);
  return parts.join("\n\n---\n\n");
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

function formatAskHistoryTime(
  ts: number,
  now: number,
  wiki: {
    conversationHistoryTimeJustNow: string;
    conversationHistoryTimeMinutes: string;
    conversationHistoryTimeHours: string;
    conversationHistoryTimeDays: string;
  },
): string {
  const sec = Math.floor((now - ts) / 1000);
  if (sec < 60) return wiki.conversationHistoryTimeJustNow;
  const min = Math.floor(sec / 60);
  if (min < 60) {
    return wiki.conversationHistoryTimeMinutes.replace("{n}", String(min));
  }
  const h = Math.floor(min / 60);
  if (h < 24) {
    return wiki.conversationHistoryTimeHours.replace("{n}", String(h));
  }
  const d = Math.floor(h / 24);
  return wiki.conversationHistoryTimeDays.replace("{n}", String(d));
}

function conclusionMarkdownText(c: Record<string, unknown> | null): string {
  if (!c) return "";
  for (const key of ["analysis", "markdown", "content", "text"] as const) {
    const v = c[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  return "";
}

function SourceRef({
  repository,
  s,
}: {
  repository: string;
  s: WikiAskSource;
}) {
  const { t } = useI18n();
  const editor = readEditorPref();
  const ide =
    s.file_path && s.start_line > 0
      ? buildIdeHref(editor, repository, s.file_path, s.start_line)
      : null;
  return (
    <li className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800/60">
      <div className="font-medium text-gray-900 dark:text-gray-100">{s.entity}</div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600 dark:text-gray-400">
        {s.wiki_page && (
          <Link
            to={wikiHref(repository, s.wiki_page)}
            className="text-sky-700 underline decoration-sky-200 dark:text-sky-400 dark:decoration-sky-800"
          >
            {s.wiki_page}
          </Link>
        )}
        {ide && s.file_path && (
          <a
            href={ide}
            className="font-mono text-sky-700 underline decoration-sky-200 dark:text-sky-400 dark:decoration-sky-800"
          >
            {s.file_path}:{s.start_line}
          </a>
        )}
        <span className="text-gray-400 dark:text-gray-500">
          {t.wiki.askScorePrefix} {s.relevance_score.toFixed(3)}
        </span>
      </div>
    </li>
  );
}

type Props = {
  repository: string | undefined;
};

/** Relative “time ago” clock that avoids impure Date calls during parent render. */
function ConversationRelativeWhen({
  createdAt,
  wiki,
}: {
  createdAt: number;
  wiki: {
    conversationHistoryTimeJustNow: string;
    conversationHistoryTimeMinutes: string;
    conversationHistoryTimeHours: string;
    conversationHistoryTimeDays: string;
  };
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  return <>{formatAskHistoryTime(createdAt, now, wiki)}</>;
}

export default function AskPanel({ repository }: Props) {
  const { locale, t } = useI18n();
  const isZh = locale === "zh";
  const [open, setOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [mode, setMode] = useState<"ask" | "deep">("ask");
  const [input, setInput] = useState("");
  const [deepInput, setDeepInput] = useState("");
  const {
    answer,
    sources,
    isStreaming,
    error,
    ask,
    cancel,
    reset,
    setAnswer,
    setSources,
    conversationId,
  } = useWikiAsk(repository);
  const convHistory = useConversationHistory();
  const prevStreamingRef = useRef(false);
  const questionForSaveRef = useRef("");
  const localThreadStorageIdRef = useRef<string | null>(null);
  const threadTitleRef = useRef("");
  const deepStream = useDeepSearchStream();

  const historyItems = repository ? convHistory.list(repository) : [];

  useEffect(() => {
    localThreadStorageIdRef.current = null;
    threadTitleRef.current = "";
    questionForSaveRef.current = "";
    prevStreamingRef.current = false;
  }, [repository]);

  useEffect(() => {
    const wasStreaming = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;
    if (
      !repository?.trim() ||
      !wasStreaming ||
      isStreaming ||
      error ||
      !answer.trim()
    ) {
      return;
    }
    const id = localThreadStorageIdRef.current ?? crypto.randomUUID();
    localThreadStorageIdRef.current = id;
    const existing = convHistory.get(repository, id);
    const q = questionForSaveRef.current;
    const userMsg: WikiConversationMessage = { role: "user", content: q };
    const asstMsg: WikiConversationMessage = { role: "assistant", content: answer };
    const messages = existing
      ? [...existing.messages, userMsg, asstMsg]
      : [userMsg, asstMsg];
    convHistory.save(repository, {
      id,
      title: threadTitleRef.current.trim() || q,
      messages,
      created_at: existing?.created_at ?? Date.now(),
      sources: [...sources],
    });
  }, [isStreaming, answer, error, repository, sources, convHistory]);

  if (!repository?.trim()) return null;

  const deepMarkdown = conclusionMarkdownText(deepStream.conclusion);

  return (
    <section
      id="wiki-ask-panel"
      className="rounded-xl border border-gray-200 bg-gradient-to-b from-white to-gray-50/80 shadow-sm dark:border-gray-700 dark:from-gray-900 dark:to-gray-950/80 dark:shadow-gray-950/40"
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-semibold text-gray-900 dark:text-gray-100"
      >
        <span className="inline-flex items-center gap-2">
          <MessageCircle size={18} className="text-sky-600 dark:text-sky-400" aria-hidden />
          {t.wiki.askWiki}
          {conversationId && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-normal text-gray-500 dark:bg-gray-800 dark:text-gray-400">
              {t.wiki.askThread}
            </span>
          )}
        </span>
        {open ? (
          <ChevronUp size={18} className="text-gray-500 dark:text-gray-400" />
        ) : (
          <ChevronDown size={18} className="text-gray-500 dark:text-gray-400" />
        )}
      </button>

      {open && (
        <div className="space-y-4 border-t border-gray-100 px-4 pb-4 pt-2 dark:border-gray-700">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                if (mode === "deep" && deepStream.isStreaming) deepStream.cancel();
                setMode("ask");
              }}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === "ask"
                  ? "bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300"
                  : "text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300"
              }`}
            >
              <MessageCircle size={14} /> {t.wiki.askWiki}
            </button>
            <button
              type="button"
              onClick={() => {
                if (mode === "ask" && isStreaming) cancel();
                setMode("deep");
              }}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === "deep"
                  ? "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300"
                  : "text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300"
              }`}
            >
              <Brain size={14} /> {t.search.deepResearch}
            </button>
          </div>

          {mode === "ask" ? (
            <>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {t.wiki.askEndpointHelpBefore}
                <code className="rounded bg-gray-100 px-1 dark:bg-gray-800 dark:text-gray-300">POST /api/v1/wiki/ask</code>
                {t.wiki.askEndpointHelpAfter}
              </p>

              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const q = input.trim();
                  if (!q || isStreaming) return;
                  if (!localThreadStorageIdRef.current) {
                    threadTitleRef.current = q;
                  }
                  questionForSaveRef.current = q;
                  void ask({ question: q });
                  setInput("");
                }}
              >
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  rows={2}
                  placeholder={t.wiki.askQuestionPlaceholder}
                  className="min-h-[44px] flex-1 resize-y rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none ring-sky-500/30 placeholder:text-gray-400 focus:border-sky-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-700"
                />
                <div className="flex shrink-0 flex-col gap-2">
                  <button
                    type="submit"
                    disabled={isStreaming || !input.trim()}
                    className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
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
                    className="text-xs text-gray-600 hover:text-gray-900 disabled:opacity-40 dark:text-gray-400 dark:hover:text-gray-100"
                  >
                    {t.wiki.stop}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      reset();
                      setInput("");
                      localThreadStorageIdRef.current = null;
                      threadTitleRef.current = "";
                      questionForSaveRef.current = "";
                    }}
                    className="text-xs text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
                  >
                    {t.wiki.clear}
                  </button>
                </div>
              </form>

              <div className="rounded-lg border border-gray-100 bg-gray-50/80 dark:border-gray-700 dark:bg-gray-800/50">
                <button
                  type="button"
                  onClick={() => setHistoryOpen(!historyOpen)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium text-gray-700 dark:text-gray-300"
                >
                  <span className="inline-flex items-center gap-1.5">
                    <History size={14} className="text-gray-500 dark:text-gray-400" aria-hidden />
                    {t.wiki.conversationHistory}
                    {historyItems.length > 0 && (
                      <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px] font-normal text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                        {historyItems.length}
                      </span>
                    )}
                  </span>
                  {historyOpen ? (
                    <ChevronUp size={16} className="text-gray-500 dark:text-gray-400" />
                  ) : (
                    <ChevronDown size={16} className="text-gray-500 dark:text-gray-400" />
                  )}
                </button>
                {historyOpen && (
                  <div className="space-y-2 border-t border-gray-100 px-3 pb-3 pt-1 dark:border-gray-700">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          reset();
                          setInput("");
                          localThreadStorageIdRef.current = null;
                          threadTitleRef.current = "";
                          questionForSaveRef.current = "";
                        }}
                        className="rounded-md border border-gray-200 bg-white px-2.5 py-1 text-[11px] text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
                      >
                        {t.wiki.conversationHistoryNew}
                      </button>
                      <button
                        type="button"
                        disabled={historyItems.length === 0}
                        onClick={() => {
                          if (!repository?.trim()) return;
                          convHistory.clear(repository);
                          localThreadStorageIdRef.current = null;
                          threadTitleRef.current = "";
                          questionForSaveRef.current = "";
                        }}
                        className="rounded-md border border-gray-200 bg-white px-2.5 py-1 text-[11px] text-gray-700 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
                      >
                        {t.wiki.conversationHistoryClearAll}
                      </button>
                    </div>
                    {historyItems.length === 0 ? (
                      <p className="text-xs text-gray-500 dark:text-gray-400">{t.wiki.conversationHistoryEmpty}</p>
                    ) : (
                      <ul className="max-h-48 space-y-1.5 overflow-y-auto">
                        {historyItems.map((c) => (
                          <li key={c.id}>
                            <button
                              type="button"
                              onClick={() => {
                                reset();
                                setAnswer(assistantTextFromMessages(c.messages));
                                setSources(c.sources ?? []);
                                setInput("");
                                localThreadStorageIdRef.current = null;
                                threadTitleRef.current = "";
                                questionForSaveRef.current = "";
                              }}
                              className="w-full rounded-md border border-transparent px-2 py-1.5 text-left text-xs hover:border-gray-200 hover:bg-white dark:hover:border-gray-600 dark:hover:bg-gray-800/80"
                            >
                              <div className="line-clamp-2 font-medium text-gray-900 dark:text-gray-100">{c.title}</div>
                              <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-gray-500 dark:text-gray-400">
                                <span>
                                  <ConversationRelativeWhen createdAt={c.created_at} wiki={t.wiki} />
                                </span>
                                <span>
                                  {t.wiki.conversationHistoryMessages.replace(
                                    "{count}",
                                    String(c.messages.length),
                                  )}
                                </span>
                              </div>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>

              {error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
                  {error}
                </div>
              )}

              {(answer || isStreaming) && (
                <div className="rounded-lg border border-gray-100 bg-white px-4 py-3 shadow-inner dark:border-gray-700 dark:bg-gray-900">
                  <div className="prose prose-sm prose-slate max-w-none whitespace-pre-wrap dark:prose-invert">
                    {answer}
                    {isStreaming && (
                      <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-sky-500 align-middle" />
                    )}
                  </div>
                </div>
              )}

              {sources.length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    {t.wiki.sources}
                  </h4>
                  <ul className="space-y-2">
                    {sources.map((s, i) => (
                      <SourceRef key={`${s.wiki_page}-${s.entity}-${i}`} repository={repository} s={s} />
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">{t.wiki.askV2Footnote}</p>
                </div>
              )}
            </>
          ) : (
            <>
              <p className="text-xs text-gray-500 dark:text-gray-400">{t.search.deepResearchDesc}</p>
              <p className="text-xs text-amber-800/90 dark:text-amber-300/90">{t.wiki.deepResearchScopeNote}</p>
              <form
                className="flex flex-col gap-2 sm:flex-row"
                onSubmit={(e) => {
                  e.preventDefault();
                  const q = deepInput.trim();
                  if (!q || deepStream.isStreaming) return;
                  void deepStream.start({ query: q, max_iterations: 3 });
                }}
              >
                <textarea
                  value={deepInput}
                  onChange={(e) => setDeepInput(e.target.value)}
                  rows={3}
                  placeholder={t.search.deepPlaceholder}
                  className="min-h-[72px] flex-1 resize-y rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none ring-amber-500/30 placeholder:text-gray-400 focus:border-amber-400 focus:ring-2 dark:border-amber-900 dark:bg-gray-900 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-amber-500 dark:focus:ring-amber-800"
                />
                <div className="flex shrink-0 flex-col gap-2 sm:w-auto">
                  <button
                    type="submit"
                    disabled={deepStream.isStreaming || !deepInput.trim()}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50 dark:bg-amber-600 dark:hover:bg-amber-500"
                  >
                    {deepStream.isStreaming && <Loader2 className="size-4 animate-spin" />}
                    {deepStream.isStreaming ? t.search.deepSearching : t.search.searchBtn}
                  </button>
                  <button
                    type="button"
                    onClick={() => deepStream.cancel()}
                    disabled={!deepStream.isStreaming}
                    className="text-xs text-gray-600 hover:text-gray-900 disabled:opacity-40 dark:text-gray-400 dark:hover:text-gray-100"
                  >
                    {t.wiki.stop}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      deepStream.cancel();
                      setDeepInput("");
                    }}
                    className="text-xs text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
                  >
                    {t.wiki.clear}
                  </button>
                </div>
              </form>

              {deepStream.error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
                  {deepStream.error}
                </div>
              )}

              {(deepStream.stages.length > 0 || deepStream.isStreaming) && (
                <div className="space-y-3">
                  <DeepResearchTimeline stages={deepStream.stages} isZh={isZh} />
                  {deepMarkdown ? (
                    <div className="rounded-lg border border-gray-100 bg-white px-4 py-3 shadow-inner dark:border-gray-700 dark:bg-gray-900">
                      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        {t.search.analysis}
                      </h4>
                      <div className="prose prose-sm prose-slate max-w-none dark:prose-invert">
                        <MarkdownRenderer content={deepMarkdown} />
                      </div>
                    </div>
                  ) : deepStream.conclusion ? (
                    <div className="rounded-lg border border-gray-100 bg-white px-4 py-3 shadow-inner dark:border-gray-700 dark:bg-gray-900">
                      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                        {t.search.analysis}
                      </h4>
                      <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300">
                        {JSON.stringify(deepStream.conclusion, null, 2)}
                      </pre>
                    </div>
                  ) : null}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
