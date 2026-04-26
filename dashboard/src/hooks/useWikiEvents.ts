import { useEffect, useRef } from "react";
import { API_BASE, getToken } from "../api/client";
import type { WikiEvent } from "./wikiTypes";

export function useWikiEvents(businessId: string, onEvent: (event: WikiEvent) => void) {
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!businessId) return;

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
    };
  }, [businessId]);
}
