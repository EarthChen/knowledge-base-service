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

  const regenerate = useCallback(
    async (incremental = true) => {
      if (!businessId.trim() || inFlightRef.current) return;
      inFlightRef.current = true;
      setIsPending(true);
      setProgress(null);
      try {
        const lang = locale === "zh" ? "zh" : "en";
        const res = await businessWikiGenerate(businessId.trim(), lang, incremental);
        const tid = res.task_id ? String(res.task_id) : "";
        if (!tid) {
          toast("success", t.wiki.regenerateStarted);
          await invalidateWikiQueriesForBusiness(queryClient, businessId);
          return;
        }
        toast("info", t.wiki.regenerateRunning);
        const maxAttempts = 120;
        for (let i = 0; i < maxAttempts; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          if (!mountedRef.current) break;
          const st: WikiAsyncTask = await businessWikiTaskStatus(tid);
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
            toast("success", t.wiki.regenerateComplete);
            await invalidateWikiQueriesForBusiness(queryClient, businessId);
            return;
          }
          if (st.status === "failed") {
            const err = st.error;
            const detail =
              err && typeof err === "object" && "detail" in err
                ? String((err as { detail?: unknown }).detail ?? err)
                : err
                  ? JSON.stringify(err)
                  : t.common.unknown;
            toast("error", t.wiki.regenerateFailed.replace("{detail}", detail));
            return;
          }
        }
        toast("error", t.wiki.regenerateTimeout);
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
    [businessId, locale, t, toast, queryClient],
  );

  return { regenerate, isPending, progress };
}
