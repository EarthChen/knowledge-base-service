import { useCallback, useState, type FormEvent } from "react";
import { Loader2, Send, Sparkles } from "lucide-react";
import ReactDiffViewer from "react-diff-viewer-continued";
import { useI18n } from "../../i18n/context";
import { useWikiEditSession, type EditEvent } from "../../hooks/useWikiEditSession";

interface Props {
  pageUid: string;
  currentContent: string;
  businessId: string;
  onContentApplied?: (newContent: string) => void;
}

interface ChatTurn {
  id: string;
  role: "user";
  content: string;
}

function summarizeEvent(ev: EditEvent): string | null {
  if (ev.type === "thinking" && typeof ev.text === "string" && ev.text.trim()) return ev.text;
  if (ev.type === "tool_call" && typeof ev.tool === "string") return ev.tool;
  if (ev.type === "tool_result" && typeof ev.tool === "string") return `${ev.tool}: ${String(ev.summary ?? "")}`;
  if (ev.type === "content") return null;
  if (ev.type === "error" && typeof ev.message === "string") return ev.message;
  return null;
}

export default function WikiEditPanel({
  pageUid,
  currentContent,
  businessId,
  onContentApplied,
}: Props) {
  const { t } = useI18n();
  const ep = t.wiki.edit_panel;
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const {
    sessionId,
    events,
    isStreaming,
    editedContent,
    error,
    createSession,
    sendMessage,
    applyEdit,
    discardSession,
  } = useWikiEditSession(pageUid);

  void businessId;

  const canUse = Boolean(pageUid.trim());

  const onSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const text = prompt.trim();
      if (!text || isStreaming || !canUse || !currentContent.trim()) return;
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}`;
      setMessages((m) => [...m, { id, role: "user", content: text }]);
      setPrompt("");
      if (!sessionId) await createSession(text, currentContent);
      else await sendMessage(text);
    },
    [prompt, isStreaming, canUse, currentContent, sessionId, createSession, sendMessage],
  );

  const handleApply = useCallback(async () => {
    if (!sessionId || isStreaming) return;
    const result = await applyEdit();
    if (result?.content != null && onContentApplied) onContentApplied(result.content);
    await discardSession();
    setMessages([]);
  }, [sessionId, isStreaming, applyEdit, discardSession, onContentApplied]);

  const handleDiscard = useCallback(async () => {
    await discardSession();
    setMessages([]);
    setPrompt("");
  }, [discardSession]);

  if (!canUse) return null;

  return (
    <section
      id="wiki-edit-panel"
      className="rounded-xl border border-gray-200 bg-gradient-to-b from-white to-gray-50/80 shadow-sm dark:border-gray-700 dark:from-gray-900 dark:to-gray-950/80 dark:shadow-gray-950/40"
    >
      <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <Sparkles size={18} className="text-violet-600 dark:text-violet-400" aria-hidden />
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{ep.title}</span>
      </div>

      <div className="space-y-3 border-t border-gray-100 px-4 pb-4 pt-3 dark:border-gray-700">
        {!currentContent.trim() && (
          <p className="text-xs text-amber-800 dark:text-amber-300">{ep.session_expired}</p>
        )}
        <form className="flex gap-2" onSubmit={(ev) => void onSubmit(ev)}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={2}
            placeholder={ep.placeholder}
            disabled={isStreaming || !currentContent.trim()}
            className="min-h-[44px] flex-1 resize-y rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none ring-sky-500/30 placeholder:text-gray-400 focus:border-sky-400 focus:ring-2 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-700"
          />
          <button
            type="submit"
            disabled={isStreaming || !prompt.trim() || !currentContent.trim()}
            className="inline-flex h-fit shrink-0 items-center justify-center rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
            aria-label={ep.send}
          >
            {isStreaming ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Send className="size-4" aria-hidden />
            )}
          </button>
        </form>

        {(messages.length > 0 || events.length > 0) && (
          <div className="max-h-56 space-y-2 overflow-y-auto rounded-lg border border-gray-100 bg-gray-50/80 p-2 text-xs dark:border-gray-700 dark:bg-gray-800/40">
            {messages.map((m) => (
              <div
                key={m.id}
                className="rounded-md bg-white px-2 py-1.5 text-gray-800 shadow-sm dark:bg-gray-900 dark:text-gray-200"
              >
                {m.content}
              </div>
            ))}
            {isStreaming && events.length === 0 && (
              <div className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden />
                <span>{ep.thinking}</span>
              </div>
            )}
            {events.map((ev, i) => {
              if (ev.type === "thinking") {
                return (
                  <div
                    key={`ev-${i}`}
                    className="flex items-center gap-2 text-[11px] text-violet-700 dark:text-violet-400"
                  >
                    <Loader2 className="size-3 animate-spin opacity-70" aria-hidden />
                    <span>{summarizeEvent(ev) ?? ep.thinking}</span>
                  </div>
                );
              }
              if (ev.type === "tool_call" || ev.type === "tool_result") {
                const detail = summarizeEvent(ev);
                return (
                  <div
                    key={`ev-${i}`}
                    className="rounded-md border border-sky-200 bg-sky-50 px-2 py-1 font-mono text-[11px] text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-200"
                  >
                    <span className="font-semibold">{ep.tool_call}</span>
                    {detail ? <span>: {detail}</span> : null}
                  </div>
                );
              }
              if (ev.type === "content") {
                return (
                  <p key={`ev-${i}`} className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100">
                    {ep.diff_title}
                  </p>
                );
              }
              if (ev.type === "error") {
                return (
                  <div key={`ev-${i}`} className="text-[11px] text-red-700 dark:text-red-400">
                    {ep.error}
                    {typeof ev.message === "string" ? `: ${ev.message}` : ""}
                  </div>
                );
              }
              return null;
            })}
            {isStreaming && events.length > 0 && (
              <div className="flex items-center gap-2 text-[11px] text-gray-500 dark:text-gray-400">
                <Loader2 className="size-3 animate-spin opacity-70" aria-hidden />
                <span>{ep.thinking}</span>
              </div>
            )}
          </div>
        )}

        {editedContent != null && editedContent !== "" && (
          <div>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {ep.diff_title}
            </h4>
            <div className="max-h-80 overflow-auto rounded-lg border border-gray-200 dark:border-gray-700">
              <ReactDiffViewer
                oldValue={currentContent}
                newValue={editedContent}
                splitView={false}
                leftTitle=""
                rightTitle=""
              />
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </div>
        )}

        {(sessionId || editedContent != null) && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={isStreaming || editedContent == null || editedContent === ""}
              onClick={() => void handleApply()}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50 dark:bg-emerald-700 dark:hover:bg-emerald-600"
            >
              {ep.apply}
            </button>
            <button
              type="button"
              disabled={isStreaming}
              onClick={() => void handleDiscard()}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              {ep.discard}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
