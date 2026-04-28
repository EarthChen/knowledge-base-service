import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, businessWikiGenerate, businessWikiTaskStatus } from "../api/client";
import type { WikiAsyncTask } from "../api/types";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { invalidateWikiQueriesForBusiness } from "./invalidateWikiQueries";

export interface WikiRegenProgress {
  totalRepos: number;
  completedRepos: number;
  currentRepo: string;
  progressPct: number;
  skippedRepos: number;
}

const STORAGE_KEY_PREFIX = "kb_wiki_active_task:";

function saveActiveTask(businessId: string, taskId: string) {
  try {
    localStorage.setItem(`${STORAGE_KEY_PREFIX}${businessId}`, taskId);
  } catch { /* ignore */ }
}

function loadActiveTask(businessId: string): string | null {
  try {
    return localStorage.getItem(`${STORAGE_KEY_PREFIX}${businessId}`);
  } catch {
    return null;
  }
}

function clearActiveTask(businessId: string) {
  try {
    localStorage.removeItem(`${STORAGE_KEY_PREFIX}${businessId}`);
  } catch { /* ignore */ }
}

export function useWikiRegenerate(businessId: string) {
  const [isPending, setIsPending] = useState(false);
  const [progress, setProgress] = useState<WikiRegenProgress | null>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { locale, t } = useI18n();

  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const pollTask = useCallback(
    async (tid: string, showToasts: boolean) => {
      const maxAttempts = 120;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        if (!mountedRef.current) break;
        let st: WikiAsyncTask;
        try {
          st = await businessWikiTaskStatus(tid);
        } catch {
          continue;
        }
        if (st.progress_pct !== undefined) {
          if (!mountedRef.current) break;
          setProgress({
            totalRepos: Number(st.total_repos) || 0,
            completedRepos: Number(st.completed_repos) || 0,
            currentRepo: st.current_repo ?? "",
            progressPct: Number(st.progress_pct) || 0,
            skippedRepos:
              typeof st.skipped_repos === "number"
                ? st.skipped_repos
                : Array.isArray(st.skipped_repos)
                  ? st.skipped_repos.length
                  : 0,
          });
        }
        if (st.status === "completed") {
          clearActiveTask(businessId);
          if (showToasts) toast("success", t.wiki.regenerateComplete);
          await invalidateWikiQueriesForBusiness(queryClient, businessId);
          return;
        }
        if (st.status === "failed") {
          clearActiveTask(businessId);
          if (showToasts) {
            const err = st.error;
            const detail =
              err && typeof err === "object" && "detail" in err
                ? String((err as { detail?: unknown }).detail ?? err)
                : err
                  ? JSON.stringify(err)
                  : t.common.unknown;
            toast("error", t.wiki.regenerateFailed.replace("{detail}", detail));
          }
          return;
        }
      }
      clearActiveTask(businessId);
      if (showToasts) toast("error", t.wiki.regenerateTimeout);
    },
    [businessId, t, toast, queryClient],
  );

  // On mount / businessId change, check for a persisted active task and resume polling
  useEffect(() => {
    if (!businessId.trim()) return;
    const savedTaskId = loadActiveTask(businessId);
    if (!savedTaskId || inFlightRef.current) return;

    let cancelled = false;
    inFlightRef.current = true;
    setIsPending(true);
    setProgress(null);

    (async () => {
      try {
        const st = await businessWikiTaskStatus(savedTaskId);
        if (cancelled) return;
        if (st.status === "completed" || st.status === "failed") {
          clearActiveTask(businessId);
          return;
        }
        await pollTask(savedTaskId, true);
      } catch {
        clearActiveTask(businessId);
      } finally {
        inFlightRef.current = false;
        if (!cancelled && mountedRef.current) {
          setIsPending(false);
          setProgress(null);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [businessId]);

  const regenerate = useCallback(
    async (incremental = true) => {
      if (!businessId.trim() || inFlightRef.current) return;
      inFlightRef.current = true;
      setIsPending(true);
      setProgress(null);
      try {
        const lang = locale === "zh" ? "zh" : "en";
        const mode = incremental ? "structure" : "full";
        const res = await businessWikiGenerate(businessId.trim(), lang, incremental, mode);
        const tid = res.task_id ? String(res.task_id) : "";
        if (!tid) {
          toast("success", t.wiki.regenerateStarted);
          await invalidateWikiQueriesForBusiness(queryClient, businessId);
          return;
        }
        saveActiveTask(businessId, tid);
        toast("info", t.wiki.regenerateRunning);
        await pollTask(tid, true);
      } catch (e: unknown) {
        if (e instanceof ApiError && e.status === 409) {
          toast("error", t.wiki.regenerateConflict);
        } else {
          toast("error", getErrorMessage(e, t.common.unexpectedError));
        }
      } finally {
        inFlightRef.current = false;
        if (mountedRef.current) {
          setIsPending(false);
          setProgress(null);
        }
      }
    },
    [businessId, locale, t, toast, queryClient, pollTask],
  );

  return { regenerate, isPending, progress };
}
