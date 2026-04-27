import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { businessWikiGenerate, wikiTaskStatus } from "../api/client";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { invalidateWikiQueriesForBusiness } from "./invalidateWikiQueries";

export function useWikiRegenerate(businessId: string) {
  const [isPending, setIsPending] = useState(false);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { locale, t } = useI18n();

  const regenerate = useCallback(async () => {
    if (!businessId.trim() || isPending) return;
    setIsPending(true);
    try {
      const lang = locale === "zh" ? "zh" : "en";
      const res = await businessWikiGenerate(businessId.trim(), lang);
      const tid = res.task_id ? String(res.task_id) : "";
      if (!tid) {
        toast("success", t.wiki.regenerateStarted);
        await invalidateWikiQueriesForBusiness(queryClient, businessId);
        return;
      }
      toast("info", t.wiki.regenerateRunning);
      const maxAttempts = 45;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const st = await wikiTaskStatus(tid);
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
    } catch (e) {
      toast("error", getErrorMessage(e, t.common.unexpectedError));
    } finally {
      setIsPending(false);
    }
  }, [businessId, isPending, locale, t, toast, queryClient]);

  return { regenerate, isPending };
}
