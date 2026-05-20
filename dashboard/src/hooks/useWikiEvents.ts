import { useEffect, useRef, useState } from "react";
import { API_BASE, authHeaders } from "../api/client";
import type { WikiEvent } from "./wikiTypes";

export type WikiEventsConnectionStatus = "connected" | "reconnecting" | "disconnected";

export function useWikiEvents(
  businessId: string,
  onEvent: (event: WikiEvent) => void,
  enabled: boolean = true,
): { connectionStatus: WikiEventsConnectionStatus } {
  const onEventRef = useRef(onEvent);
  const [connectionStatus, setConnectionStatus] = useState<WikiEventsConnectionStatus>("disconnected");

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!businessId.trim() || !enabled) {
      setConnectionStatus("disconnected");
      return;
    }

    let abortController: AbortController | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let retryMs = 1000;
    let stopped = false;

    const connect = async () => {
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
      }
      abortController?.abort();

      const ac = new AbortController();
      abortController = ac;

      const params = new URLSearchParams({ business_id: businessId });
      const url = `${API_BASE}/wiki/events?${params.toString()}`;

      try {
        const res = await fetch(url, {
          headers: { ...authHeaders(), Accept: "text/event-stream" },
          signal: ac.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`SSE connect failed: ${res.status}`);
        }

        retryMs = 1000;
        setConnectionStatus("connected");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sep: number;
          while ((sep = buffer.indexOf("\n\n")) >= 0) {
            const rawBlock = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            for (const line of rawBlock.split("\n")) {
              if (!line.startsWith("data:")) continue;
              const dataStr = line.slice(5).trimStart();
              if (!dataStr) continue;
              try {
                const event = JSON.parse(dataStr) as WikiEvent;
                if (event.business_id?.trim() !== businessId.trim()) continue;
                onEventRef.current(event);
              } catch {
                /* ignore malformed */
              }
            }
          }
        }
        if (!stopped) throw new Error("stream ended");
      } catch (e) {
        if (stopped) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        setConnectionStatus("reconnecting");
        const delay = retryMs;
        retryMs = Math.min(retryMs * 2, 30_000);
        reconnectTimeout = setTimeout(() => {
          reconnectTimeout = null;
          connect();
        }, delay);
      }
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      abortController?.abort();
      setConnectionStatus("disconnected");
    };
  }, [businessId, enabled]);

  return { connectionStatus };
}
