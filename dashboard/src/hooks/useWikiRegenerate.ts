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
  const businessIdRef = useRef(businessId);
  businessIdRef.current = businessId;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      inFlightRef.current = false;
    };
  }, []);

  const isActiveBusiness = useCallback((id: string) => businessIdRef.current === id, []);

  const pollTask = useCallback(
    async (tid: string, showToasts: boolean) => {
      const pollForBusiness = businessId;
      const maxAttempts = 120;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        if (!mountedRef.current || !isActiveBusiness(pollForBusiness)) break;
        let st: WikiAsyncTask;
        try {
          st = await businessWikiTaskStatus(tid);
        } catch {
          continue;
        }
        if (!isActiveBusiness(pollForBusiness)) break;
        if (st.progress_pct !== undefined) {
          if (!mountedRef.current || !isActiveBusiness(pollForBusiness)) break;
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
          clearActiveTask(pollForBusiness);
          if (showToasts && isActiveBusiness(pollForBusiness)) {
            toast("success", t.wiki.regenerateComplete);
          }
          if (isActiveBusiness(pollForBusiness)) {
            await invalidateWikiQueriesForBusiness(queryClient, pollForBusiness);
          }
          return;
        }
        if (st.status === "failed") {
          clearActiveTask(pollForBusiness);
          if (showToasts && isActiveBusiness(pollForBusiness)) {
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
        if (st.status === "cancelled") {
          clearActiveTask(pollForBusiness);
          if (showToasts && isActiveBusiness(pollForBusiness)) {
            toast("info", t.wiki.taskCancelled);
          }
          return;
        }
      }
      if (mountedRef.current && inFlightRef.current && isActiveBusiness(pollForBusiness)) {
        if (showToasts) {
          toast(
            "error",
            locale === "zh"
              ? "Wiki 生成超时，请稍后检查状态"
              : "Wiki generation timed out. Please check status later.",
          );
        }
        clearActiveTask(pollForBusiness);
        setIsPending(false);
        setProgress(null);
        inFlightRef.current = false;
      }
    },
    [businessId, locale, t, toast, queryClient, isActiveBusiness],
  );

  // On mount / businessId change, check for a persisted active task and resume polling
  useEffect(() => {
    if (!businessId.trim()) return;
    const resumeForBusiness = businessId;
    const savedTaskId = loadActiveTask(resumeForBusiness);
    if (!savedTaskId || inFlightRef.current) return;

    let cancelled = false;
    inFlightRef.current = true;
    setIsPending(true);
    setProgress(null);

    (async () => {
      try {
        const st = await businessWikiTaskStatus(savedTaskId);
        if (cancelled || !isActiveBusiness(resumeForBusiness)) return;
        if (st.status === "completed" || st.status === "failed" || st.status === "cancelled") {
          if (st.status === "completed" && isActiveBusiness(resumeForBusiness)) {
            await invalidateWikiQueriesForBusiness(queryClient, resumeForBusiness);
          }
          clearActiveTask(resumeForBusiness);
          return;
        }
        await pollTask(savedTaskId, true);
      } catch {
        if (isActiveBusiness(resumeForBusiness)) {
          clearActiveTask(resumeForBusiness);
        }
      } finally {
        inFlightRef.current = false;
        if (!cancelled && mountedRef.current && isActiveBusiness(resumeForBusiness)) {
          setIsPending(false);
          setProgress(null);
        }
      }
    })();

    return () => {
      cancelled = true;
      inFlightRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [businessId]);

  const regenerate = useCallback(
    async (incremental = true) => {
      if (!businessId.trim() || inFlightRef.current) return;
      const regenForBusiness = businessId.trim();
      inFlightRef.current = true;
      setIsPending(true);
      setProgress(null);
      try {
        const lang = locale === "zh" ? "zh" : "en";
        const mode = "full";
        const res = await businessWikiGenerate(regenForBusiness, lang, incremental, mode);
        if (!isActiveBusiness(regenForBusiness)) return;
        const tid = res.task_id ? String(res.task_id) : "";
        if (!tid) {
          toast("success", t.wiki.regenerateStarted);
          await invalidateWikiQueriesForBusiness(queryClient, regenForBusiness);
          return;
        }
        saveActiveTask(regenForBusiness, tid);
        toast("info", t.wiki.regenerateRunning);
        await pollTask(tid, true);
      } catch (e: unknown) {
        if (!isActiveBusiness(regenForBusiness)) return;
        if (e instanceof ApiError && e.status === 409) {
          toast("error", t.wiki.regenerateConflict);
        } else {
          toast("error", getErrorMessage(e, t.common.unexpectedError));
        }
      } finally {
        inFlightRef.current = false;
        if (mountedRef.current && isActiveBusiness(regenForBusiness)) {
          setIsPending(false);
          setProgress(null);
        }
      }
    },
    [businessId, locale, t, toast, queryClient, pollTask, isActiveBusiness],
  );

  return { regenerate, isPending, progress };
}
