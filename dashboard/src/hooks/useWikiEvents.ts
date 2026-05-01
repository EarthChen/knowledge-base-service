import { useEffect, useRef, useState } from "react";
import { API_BASE, getToken } from "../api/client";
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

    let source: EventSource | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let retryMs = 1000;

    const connect = () => {
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
      }
      source?.close();

      const params = new URLSearchParams({ business_id: businessId });
      const t = getToken();
      if (t) params.set("token", t);
      const url = `${API_BASE}/wiki/events?${params.toString()}`;
      const es = new EventSource(url);

      es.onopen = () => {
        retryMs = 1000;
        setConnectionStatus("connected");
      };

      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as WikiEvent;
          if (event.business_id?.trim() !== businessId.trim()) return;
          onEventRef.current(event);
        } catch {
          /* ignore malformed events */
        }
      };

      es.onerror = () => {
        es.close();
        setConnectionStatus("reconnecting");
        const delay = retryMs;
        retryMs = Math.min(retryMs * 2, 30_000);
        reconnectTimeout = setTimeout(() => {
          reconnectTimeout = null;
          connect();
        }, delay);
      };

      source = es;
    };

    connect();

    return () => {
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      source?.close();
      setConnectionStatus("disconnected");
    };
  }, [businessId, enabled]);

  return { connectionStatus };
}
