import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";

function useReviewErrorToast(context: string) {
  const { toast } = useToast();
  const { t } = useI18n();
  return (error: Error) => {
    console.error(context, error.message);
    toast("error", getErrorMessage(error, t.common.unexpectedError));
  };
}

export function useSetPageReview() {
  const qc = useQueryClient();
  const onError = useReviewErrorToast("Failed to set page review:");
  return useMutation<unknown, ApiError, { pagePath: string; status: string; notes: string }>({
    mutationFn: ({ pagePath, status, notes }) =>
      api(`/wiki/pages/${encodeURIComponent(pagePath)}/review`, {
        method: "POST",
        body: JSON.stringify({ status, notes }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wiki.all });
    },
    onError,
  });
}

export function useBatchReview() {
  const qc = useQueryClient();
  const onError = useReviewErrorToast("Failed to batch review:");
  return useMutation<
    unknown,
    ApiError,
    { businessId: string; reviews: Array<{ page_path: string; status: string; notes?: string }> }
  >({
    mutationFn: ({ businessId, reviews }) =>
      api("/wiki/review/batch", {
        method: "POST",
        body: JSON.stringify({ business_id: businessId, reviews }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wiki.all });
    },
    onError,
  });
}

export function useRegeneratePage() {
  const qc = useQueryClient();
  const onError = useReviewErrorToast("Failed to regenerate page:");
  return useMutation<{ task_id: string }, ApiError, { pagePath: string; healHints?: string }>({
    mutationFn: ({ pagePath, healHints }) =>
      api(`/wiki/pages/${encodeURIComponent(pagePath)}/regenerate`, {
        method: "POST",
        body: JSON.stringify({ heal_hints: healHints ?? "" }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wiki.all });
    },
    onError,
  });
}
