import { useState, useCallback, useRef } from "react";
import type { StageEvent } from "../components/DeepResearchTimeline";
import { API_BASE, authHeaders } from "../api/client";
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

  const start = useCallback(async (params: { query: string; max_iterations?: number }) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ stages: [], conclusion: null, isStreaming: true, error: null });

    try {
      const res = await fetch(`${API_BASE}/deep-search/stream`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(params),
        signal: controller.signal,
      });

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

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            pendingEventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && pendingEventType) {
            const evType = pendingEventType;
            try {
              const data = JSON.parse(line.slice(6));
              if (!KNOWN_DEEP_SEARCH_EVENTS.has(evType as StageEvent["type"])) {
                pendingEventType = "";
                continue;
              }
              const status: StageEvent["status"] =
                evType === "progress" || evType === "plan" ? "active" : "done";
              const event: StageEvent = {
                type: evType as StageEvent["type"],
                data,
                status,
              };

              setState((prev) => {
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

      setState((prev) => ({ ...prev, isStreaming: false }));
    } catch (err) {
      if (!(err instanceof Error) || err.name !== "AbortError") {
        setState((prev) => ({
          ...prev,
          isStreaming: false,
          error: getErrorMessage(err, t.common.unexpectedError),
        }));
      }
    }
  }, [t]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((prev) => ({ ...prev, isStreaming: false }));
  }, []);

  return { ...state, start, cancel };
}
