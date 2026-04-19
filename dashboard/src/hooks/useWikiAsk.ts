import { useCallback, useRef, useState } from "react";
import { getToken, getCurrentBusiness } from "../api/client";
import type { WikiAskSource } from "./wikiTypes";

const API_BASE = "/api/v1";

export type WikiAskBody = {
  repository: string;
  question: string;
  scope?: string | null;
  conversation_id?: string | null;
  mode?: "hybrid" | "graph" | "semantic" | "keyword";
};

function authHeaders(): Record<string, string> {
  const t = getToken();
  const biz = getCurrentBusiness();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (t) h.Authorization = `Bearer ${t}`;
  if (biz) h["X-Business-Id"] = biz;
  return h;
}

/** Parse SSE stream from POST /wiki/ask */
async function consumeWikiAskStream(
  res: Response,
  handlers: {
    onAnswerDelta?: (full: string, delta: string) => void;
    onSources?: (sources: WikiAskSource[]) => void;
    onComplete?: (data: {
      conversation_id: string;
      tokens_used: number;
    }) => void;
    onError?: (message: string) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (!signal?.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const rawBlock = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawBlock.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      const dataStr = dataLines.join("\n");
      if (!dataStr) continue;

      let data: Record<string, unknown>;
      try {
        data = JSON.parse(dataStr) as Record<string, unknown>;
      } catch {
        continue;
      }

      if (eventName === "wiki-answer") {
        handlers.onAnswerDelta?.(
          String(data.content ?? ""),
          String(data.delta ?? ""),
        );
      } else if (eventName === "wiki-sources") {
        const raw = data.sources;
        if (Array.isArray(raw)) {
          const sources = raw.map((s) => {
            const o = s as Record<string, unknown>;
            return {
              entity: String(o.entity ?? ""),
              file_path: String(o.file_path ?? ""),
              start_line: Number(o.start_line ?? 0),
              wiki_page: String(o.wiki_page ?? ""),
              relevance_score: Number(o.relevance_score ?? 0),
            } satisfies WikiAskSource;
          });
          handlers.onSources?.(sources);
        }
      } else if (eventName === "wiki-answer-complete") {
        handlers.onComplete?.({
          conversation_id: String(data.conversation_id ?? ""),
          tokens_used: Number(data.tokens_used ?? 0),
        });
      } else if (eventName === "error") {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : typeof data.error === "string"
              ? data.error
              : JSON.stringify(data);
        handlers.onError?.(detail);
      }
    }
  }
}

export function useWikiAsk(repository: string | undefined) {
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<WikiAskSource[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setAnswer("");
    setSources([]);
    setError(null);
    setConversationId(undefined);
  }, []);

  const ask = useCallback(
    async (body: Omit<WikiAskBody, "repository">) => {
      if (!repository?.trim()) return;
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      setIsStreaming(true);
      setError(null);
      setAnswer("");
      setSources([]);

      const payload: WikiAskBody = {
        repository,
        question: body.question,
        scope: body.scope ?? null,
        conversation_id: body.conversation_id ?? conversationId ?? null,
        mode: body.mode ?? "hybrid",
      };

      let res: Response;
      try {
        res = await fetch(`${API_BASE}/wiki/ask`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(payload),
          signal: ac.signal,
        });
      } catch (e) {
        setIsStreaming(false);
        if ((e as Error).name === "AbortError") return;
        setError((e as Error).message || "Request failed");
        return;
      }

      if (!res.ok) {
        const text = await res.text();
        setIsStreaming(false);
        setError(text || res.statusText);
        return;
      }

      try {
        await consumeWikiAskStream(
          res,
          {
            onAnswerDelta: (full) => setAnswer(full),
            onSources: setSources,
            onComplete: (d) => setConversationId(d.conversation_id),
            onError: (msg) => setError(msg),
          },
          ac.signal,
        );
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError((e as Error).message || "Stream failed");
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [repository, conversationId],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  return {
    answer,
    sources,
    conversationId,
    isStreaming,
    error,
    ask,
    cancel,
    reset,
    setAnswer,
    setSources,
    setConversationId,
  };
}
