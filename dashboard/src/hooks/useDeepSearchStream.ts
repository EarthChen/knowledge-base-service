import { useState, useCallback, useRef } from "react";
import type { StageEvent } from "../components/DeepResearchTimeline";
import { API_BASE, authHeaders } from "../api/client";

type StreamState = {
  stages: StageEvent[];
  conclusion: Record<string, unknown> | null;
  isStreaming: boolean;
  error: string | null;
};

export function useDeepSearchStream() {
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

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEventType = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && currentEventType) {
            try {
              const data = JSON.parse(line.slice(6));
              const event: StageEvent = {
                type: currentEventType as StageEvent["type"],
                data,
                status: "done",
              };

              setState((prev) => {
                const updated = prev.stages.map((s) =>
                  s.status === "active" ? { ...s, status: "done" as const } : s,
                );

                if (currentEventType === "conclusion") {
                  return {
                    ...prev,
                    stages: [...updated, { ...event, status: "done" }],
                    conclusion: data,
                    isStreaming: false,
                  };
                }

                if (currentEventType === "progress" || currentEventType === "plan") {
                  event.status = "active";
                }

                return {
                  ...prev,
                  stages: [...updated, event],
                };
              });

              currentEventType = "";
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }

      setState((prev) => ({ ...prev, isStreaming: false }));
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setState((prev) => ({
          ...prev,
          isStreaming: false,
          error: (err as Error).message,
        }));
      }
    }
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((prev) => ({ ...prev, isStreaming: false }));
  }, []);

  return { ...state, start, cancel };
}
