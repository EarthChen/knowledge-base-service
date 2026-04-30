import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function useSetPageReview() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { pagePath: string; status: string; notes: string }>({
    mutationFn: ({ pagePath, status, notes }) =>
      api(`/wiki/pages/${encodeURIComponent(pagePath)}/review`, {
        method: "POST",
        body: JSON.stringify({ status, notes }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}

export function useBatchReview() {
  const qc = useQueryClient();
  return useMutation<
    unknown,
    Error,
    { businessId: string; reviews: Array<{ page_path: string; status: string; notes?: string }> }
  >({
    mutationFn: ({ businessId, reviews }) =>
      api("/wiki/review/batch", {
        method: "POST",
        body: JSON.stringify({ business_id: businessId, reviews }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}

export function useRegeneratePage() {
  const qc = useQueryClient();
  return useMutation<{ task_id: string }, Error, { pagePath: string; healHints?: string }>({
    mutationFn: ({ pagePath, healHints }) =>
      api(`/wiki/pages/${encodeURIComponent(pagePath)}/regenerate`, {
        method: "POST",
        body: JSON.stringify({ heal_hints: healHints ?? "" }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}
