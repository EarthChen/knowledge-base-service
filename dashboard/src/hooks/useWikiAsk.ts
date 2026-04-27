import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../api/client";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import type { ReasoningPathData, ReasoningStage, WikiAskSource } from "./wikiTypes";

const API_BASE = "/api/v1";

export type WikiAskBody = {
  repository: string;
  question: string;
  scope?: string | null;
  conversation_id?: string | null;
  mode?: "hybrid" | "graph" | "semantic" | "keyword";
};

function parseReasoningPath(raw: unknown): ReasoningPathData | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const stagesRaw = o.stages;
  if (!Array.isArray(stagesRaw)) return null;
  const stages: ReasoningStage[] = stagesRaw.map((row) => {
    const s = row as Record<string, unknown>;
    const hits = s.entity_hits;
    const entity_hits = Array.isArray(hits) ? hits.map((x) => String(x)) : [];
    const meta = s.metadata;
    return {
      stage_name: String(s.stage_name ?? ""),
      retriever: String(s.retriever ?? ""),
      entity_hits,
      score: s.score == null || typeof s.score !== "number" ? null : s.score,
      metadata: meta && typeof meta === "object" && !Array.isArray(meta) ? (meta as Record<string, unknown>) : {},
    };
  });
  const ae = o.answer_entities;
  const answer_entities = Array.isArray(ae) ? ae.map((x) => String(x)) : [];
  return { stages, answer_entities };
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
      reasoning_path: ReasoningPathData | null;
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
        const rp = parseReasoningPath(data.reasoning_path);
        handlers.onComplete?.({
          conversation_id: String(data.conversation_id ?? ""),
          tokens_used: Number(data.tokens_used ?? 0),
          reasoning_path: rp,
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
  const { t } = useI18n();
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<WikiAskSource[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reasoningPath, setReasoningPath] = useState<ReasoningPathData | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const reset = useCallback(() => {
    setAnswer("");
    setSources([]);
    setError(null);
    setConversationId(undefined);
    setReasoningPath(null);
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
      setReasoningPath(null);

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
        if (e instanceof Error && e.name === "AbortError") return;
        setError(getErrorMessage(e, t.common.unexpectedError) || t.wiki.askRequestFailed);
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
            onComplete: (d) => {
              setConversationId(d.conversation_id);
              setReasoningPath(d.reasoning_path);
            },
            onError: (msg) => setError(msg),
          },
          ac.signal,
        );
      } catch (e) {
        if (!(e instanceof Error) || e.name !== "AbortError") {
          setError(getErrorMessage(e, t.common.unexpectedError) || t.wiki.askStreamFailed);
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [repository, conversationId, t],
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
    reasoningPath,
    ask,
    cancel,
    reset,
    setAnswer,
    setSources,
    setConversationId,
  };
}
