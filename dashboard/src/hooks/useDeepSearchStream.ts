import { useState, useCallback, useRef, useEffect } from "react";
import type { StageEvent } from "../components/DeepResearchTimeline";
import { apiStream } from "../api/client";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";

/** Ignore unknown SSE event names so new backend events do not affect this hook. */
const KNOWN_DEEP_SEARCH_EVENTS = new Set<StageEvent["type"]>([
  "plan",
  "progress",
  "search_done",
  "synthesis",
  "conclusion",
  "error",
  "planning",
  "evaluating",
]);

type StreamState = {
  stages: StageEvent[];
  conclusion: Record<string, unknown> | null;
  isStreaming: boolean;
  error: string | null;
};

export function useDeepSearchStream() {
  const { t } = useI18n();
  const [state, setState] = useState<StreamState>({
    stages: [],
    conclusion: null,
    isStreaming: false,
    error: null,
  });
  const abortRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      generationRef.current += 1;
    },
    [],
  );

  const start = useCallback(async (params: { query: string; max_iterations?: number }) => {
    abortRef.current?.abort();
    const generation = ++generationRef.current;
    const controller = new AbortController();
    abortRef.current = controller;

    const isCurrent = () => generationRef.current === generation;

    const patchState = (updater: (prev: StreamState) => StreamState) => {
      if (!isCurrent()) return;
      setState(updater);
    };

    patchState(() => ({ stages: [], conclusion: null, isStreaming: true, error: null }));

    try {
      const res = await apiStream("/deep-search/stream", {
        method: "POST",
        body: JSON.stringify(params),
        signal: controller.signal,
      });

      if (!isCurrent()) return;

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";
      // event: and data: lines are often split across read() chunks (separate TCP packets).
      let pendingEventType = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!isCurrent()) return;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            pendingEventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && pendingEventType) {
            const evType = pendingEventType;
            try {
              const raw = JSON.parse(line.slice(6));
              if (!KNOWN_DEEP_SEARCH_EVENTS.has(evType as StageEvent["type"])) {
                pendingEventType = "";
                continue;
              }
              const data =
                raw && typeof raw === "object" && !Array.isArray(raw)
                  ? (raw as Record<string, unknown>)
                  : {};
              /** RAG stream wraps granular stages in `event: progress` with nested `data.type`. */
              let stageType = evType as StageEvent["type"];
              if (
                evType === "progress" &&
                (data.type === "planning" || data.type === "evaluating")
              ) {
                stageType = data.type;
              }
              const status: StageEvent["status"] =
                stageType === "progress" ||
                stageType === "plan" ||
                stageType === "planning" ||
                stageType === "evaluating"
                  ? "active"
                  : "done";
              const event: StageEvent = {
                type: stageType,
                data,
                status,
              };

              patchState((prev) => {
                const updated = prev.stages.map((s) =>
                  s.status === "active" ? { ...s, status: "done" as const } : s,
                );

                if (evType === "conclusion") {
                  return {
                    ...prev,
                    stages: [...updated, { ...event, status: "done" as const }],
                    conclusion: data,
                    isStreaming: false,
                  };
                }

                return {
                  ...prev,
                  stages: [...updated, event],
                };
              });

              pendingEventType = "";
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }

      patchState((prev) => ({ ...prev, isStreaming: false }));
    } catch (err) {
      if (!(err instanceof Error) || err.name !== "AbortError") {
        patchState((prev) => ({
          ...prev,
          isStreaming: false,
          error: getErrorMessage(err, t.common.unexpectedError),
        }));
      }
    }
  }, [t]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    generationRef.current += 1;
    setState((prev) => ({ ...prev, isStreaming: false }));
  }, []);

  return { ...state, start, cancel };
}
