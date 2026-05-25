import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, apiStream } from "../api/client";

export interface EditEvent {
  type: "thinking" | "tool_call" | "tool_result" | "content" | "done" | "error";
  [key: string]: unknown;
}

export interface EditSessionState {
  sessionId: string | null;
  events: EditEvent[];
  isStreaming: boolean;
  editedContent: string | null;
  error: string | null;
}

async function consumeEditSessionStream(
  res: Response,
  handlers: {
    onEvent: (e: EditEvent) => void;
    /** Invoked once when stream ends or a terminal event arrives. */
    onTerminal: () => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminalFromPayload = false;
  while (!signal?.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const rawBlock = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const dataLines: string[] = [];
      for (const line of rawBlock.split("\n")) {
        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      const dataStr = dataLines.join("\n").trim();
      if (!dataStr) continue;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(dataStr) as Record<string, unknown>;
      } catch {
        continue;
      }
      const type = data.type;
      if (typeof type !== "string") continue;
      handlers.onEvent(data as EditEvent);
      if (type === "done" || type === "error") {
        sawTerminalFromPayload = true;
        handlers.onTerminal();
        return;
      }
    }
  }
  if (!sawTerminalFromPayload) handlers.onTerminal();
}

export function useWikiEditSession(pageUid: string) {
  const [state, setState] = useState<EditSessionState>({
    sessionId: null,
    events: [],
    isStreaming: false,
    editedContent: null,
    error: null,
  });
  const abortRef = useRef<AbortController | null>(null);
  const stateRef = useRef(state);

  useEffect(() => {
    abortRef.current?.abort();
    setState({
      sessionId: null,
      events: [],
      isStreaming: false,
      editedContent: null,
      error: null,
    });
    abortRef.current = new AbortController();
  }, [pageUid]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const startStreaming = useCallback(
    async (sessionIdForStream: string) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setState((s) => ({ ...s, isStreaming: true, error: null }));
      const path = `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${encodeURIComponent(sessionIdForStream)}/stream`;
      try {
        const res = await apiStream(path, {
          method: "GET",
          headers: { Accept: "text/event-stream" },
          signal: ac.signal,
        });
        if (!res.ok) {
          let msg = res.statusText;
          try {
            const text = await res.text();
            if (text.trim()) {
              const j = JSON.parse(text) as Record<string, unknown>;
              const detail = j.detail;
              if (typeof detail === "string") msg = detail;
              else msg = text;
            }
          } catch {
            /* leave msg */
          }
          throw new ApiError(msg, res.status, null);
        }
        await consumeEditSessionStream(
          res,
          {
            onEvent: (evt) => {
              setState((s) => {
                const next: EditSessionState = { ...s, events: [...s.events, evt] };
                if (evt.type === "content" && typeof evt.text === "string") {
                  next.editedContent = evt.text;
                }
                if (evt.type === "error") {
                  const m = evt.message;
                  next.error = typeof m === "string" ? m : s.error;
                }
                return next;
              });
            },
            onTerminal: () => {
              setState((s) => ({ ...s, isStreaming: false }));
            },
          },
          ac.signal,
        );
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (e instanceof Error && e.name === "AbortError") return;
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: e instanceof Error ? e.message : String(e),
        }));
      }
    },
    [pageUid],
  );

  const createSession = useCallback(
    async (prompt: string, currentContent: string) => {
      setState((s) => ({
        ...s,
        isStreaming: true,
        events: [],
        editedContent: null,
        error: null,
      }));
      try {
        const resp = await api<{ session_id: string }>(
          `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session`,
          {
            method: "POST",
            body: JSON.stringify({ prompt, current_content: currentContent }),
          },
        );
        const sid = resp.session_id;
        setState((s) => ({ ...s, sessionId: sid }));
        await startStreaming(sid);
        return sid;
      } catch (e) {
        setState((s) => ({
          ...s,
          isStreaming: false,
          sessionId: null,
          error: e instanceof Error ? e.message : String(e),
        }));
        return null;
      }
    },
    [pageUid, startStreaming],
  );

  const sendMessage = useCallback(
    async (prompt: string) => {
      const sid = stateRef.current.sessionId;
      if (!sid) return;
      setState((s) => ({
        ...s,
        isStreaming: true,
        editedContent: null,
        error: null,
      }));
      try {
        await api(
          `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${encodeURIComponent(sid)}/message`,
          { method: "POST", body: JSON.stringify({ prompt }) },
        );
        await startStreaming(sid);
      } catch (e) {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: e instanceof Error ? e.message : String(e),
        }));
      }
    },
    [pageUid, startStreaming],
  );

  const applyEdit = useCallback(async () => {
    const sid = stateRef.current.sessionId;
    if (!sid) return null;
    return api<{ page_uid: string; content: string }>(
      `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${encodeURIComponent(sid)}/apply`,
      { method: "POST" },
    );
  }, [pageUid]);

  const discardSession = useCallback(async () => {
    abortRef.current?.abort();
    const sid = stateRef.current.sessionId;
    if (!sid) {
      setState({
        sessionId: null,
        events: [],
        isStreaming: false,
        editedContent: null,
        error: null,
      });
      return;
    }
    try {
      await api(`/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${encodeURIComponent(sid)}`, {
        method: "DELETE",
      });
    } catch {
      // best-effort cleanup
    }
    setState({
      sessionId: null,
      events: [],
      isStreaming: false,
      editedContent: null,
      error: null,
    });
  }, [pageUid]);

  return {
    ...state,
    createSession,
    sendMessage,
    applyEdit,
    discardSession,
  };
}
