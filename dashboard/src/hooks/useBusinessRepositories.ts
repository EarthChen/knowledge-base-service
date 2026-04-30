import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface RepoListResponse {
  repositories: string[];
}

export function useBusinessRepositories(businessId: string) {
  return useQuery<RepoListResponse>({
    queryKey: ["business", businessId, "repositories"],
    queryFn: () => api(`/businesses/${encodeURIComponent(businessId)}/repositories`),
    enabled: !!businessId && businessId !== "default",
    staleTime: 30_000,
  });
}

export function useBindRepositories(businessId: string) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, string[]>({
    mutationFn: (repositories) =>
      api(`/businesses/${encodeURIComponent(businessId)}/repositories`, {
        method: "PUT",
        body: JSON.stringify({ repositories }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["business", businessId, "repositories"] });
    },
    onError: (error) => {
      console.error("Failed to bind repositories:", error.message);
    },
  });
}
