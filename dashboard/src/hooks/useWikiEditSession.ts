import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";

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

export function useWikiEditSession(pageUid: string) {
  const [state, setState] = useState<EditSessionState>({
    sessionId: null,
    events: [],
    isStreaming: false,
    editedContent: null,
    error: null,
  });
  const abortRef = useRef<AbortController | null>(null);

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
        setState((s) => ({ ...s, sessionId: resp.session_id }));
        return resp.session_id;
      } catch (e) {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: e instanceof Error ? e.message : String(e),
        }));
        return null;
      }
    },
    [pageUid],
  );

  const sendMessage = useCallback(
    async (prompt: string) => {
      if (!state.sessionId) return;
      setState((s) => ({ ...s, isStreaming: true, error: null }));
      try {
        await api(
          `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${state.sessionId}/message`,
          { method: "POST", body: JSON.stringify({ prompt }) },
        );
      } catch (e) {
        setState((s) => ({
          ...s,
          isStreaming: false,
          error: e instanceof Error ? e.message : String(e),
        }));
      }
    },
    [pageUid, state.sessionId],
  );

  const applyEdit = useCallback(async () => {
    if (!state.sessionId) return null;
    return api<{ page_uid: string; content: string }>(
      `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${state.sessionId}/apply`,
      { method: "POST" },
    );
  }, [pageUid, state.sessionId]);

  const discardSession = useCallback(async () => {
    if (!state.sessionId) return;
    abortRef.current?.abort();
    try {
      await api(
        `/wiki/pages/${encodeURIComponent(pageUid)}/edit-session/${state.sessionId}`,
        { method: "DELETE" },
      );
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
  }, [pageUid, state.sessionId]);

  return {
    ...state,
    createSession,
    sendMessage,
    applyEdit,
    discardSession,
  };
}
