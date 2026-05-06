import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";

interface RepoListResponse {
  repositories: string[];
}

export function useBusinessRepositories(businessId: string) {
  return useQuery<RepoListResponse>({
    queryKey: queryKeys.businessRepositories(businessId),
    queryFn: () => api(`/businesses/${encodeURIComponent(businessId)}/repositories`),
    enabled: !!businessId && businessId !== "default",
    staleTime: 30_000,
  });
}

export function useBindRepositories(businessId: string) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { t } = useI18n();
  return useMutation<unknown, ApiError, string[]>({
    mutationFn: (repositories) =>
      api(`/businesses/${encodeURIComponent(businessId)}/repositories`, {
        method: "PUT",
        body: JSON.stringify({ repositories }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.businessRepositories(businessId) });
    },
    onError: (error) => {
      toast("error", getErrorMessage(error, t.common.unexpectedError));
    },
  });
}
