import { useEffect, useState } from "react";
import { api } from "../api/client";

const HEARTBEAT_MS = 2 * 60 * 1000;
const POLL_MS = 30 * 1000;

export interface WikiEditorsResponse {
  editors: Array<{
    editor_id: string;
    token_prefix: string;
    last_heartbeat: number;
    label: string;
  }>;
  other_active: boolean;
  degraded?: boolean;
}

export function hasWikiEditorConflict(data: WikiEditorsResponse | null): boolean {
  if (!data) return false;
  return Boolean(data.other_active);
}

/**
 * While mounted, registers editing presence, sends heartbeats, polls for other editors, and
 * removes presence on unmount (save/cancel/navigation).
 */
export function useWikiEditingPresence(pageUid: string) {
  const [otherEditorActive, setOtherEditorActive] = useState(false);

  useEffect(() => {
    const base = `/wiki/pages/${encodeURIComponent(pageUid)}/editing`;
    const editorsPath = `/wiki/pages/${encodeURIComponent(pageUid)}/editors`;

    const pulse = () => {
      void api<unknown>(base, { method: "POST", body: "{}" });
    };
    const release = () => {
      void api<unknown>(base, { method: "DELETE" }).catch(() => undefined);
    };
    const poll = () => {
      void api<WikiEditorsResponse>(editorsPath)
        .then((r) => setOtherEditorActive(hasWikiEditorConflict(r)))
        .catch(() => setOtherEditorActive(false));
    };

    pulse();
    poll();
    const hb = window.setInterval(pulse, HEARTBEAT_MS);
    const polli = window.setInterval(poll, POLL_MS);

    return () => {
      clearInterval(hb);
      clearInterval(polli);
      release();
    };
  }, [pageUid]);

  return { otherEditorActive };
}
