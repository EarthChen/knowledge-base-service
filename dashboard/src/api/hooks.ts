import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Business,
  BusinessesResponse,
  GraphStats,
  RepositoriesResponse,
  SearchResponse,
  HybridSearchResponse,
  HealthResponse,
  IndexResponse,
  GraphExploreResponse,
  CodeSnippetResponse,
} from "./types";

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: () => api("/health", { method: "GET" }),
    refetchInterval: 30_000,
  });
}

export function useStats(repository?: string) {
  const params = repository ? `?repository=${encodeURIComponent(repository)}` : "";
  return useQuery<GraphStats>({
    queryKey: ["stats", repository],
    queryFn: () => api(`/stats${params}`, { method: "GET" }),
  });
}

export function useRepositories() {
  return useQuery<RepositoriesResponse>({
    queryKey: ["repositories"],
    queryFn: () => api("/repositories", { method: "GET" }),
  });
}

export function useSemanticSearch() {
  return useMutation<
    SearchResponse,
    Error,
    { query: string; k: number; entity_type: string }
  >({
    mutationFn: (body) =>
      api("/search", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useHybridSearch() {
  return useMutation<
    HybridSearchResponse,
    Error,
    { query: string; k: number; expand_depth: number }
  >({
    mutationFn: (body) =>
      api("/hybrid", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useGraphQuery() {
  return useMutation<Record<string, unknown>, Error, Record<string, unknown>>({
    mutationFn: (body) =>
      api("/graph", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useIndex() {
  return useMutation<IndexResponse, Error, Record<string, unknown>>({
    mutationFn: (body) =>
      api("/index", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useGraphExplore() {
  return useMutation<
    GraphExploreResponse,
    Error,
    { name: string; depth: number; limit: number }
  >({
    mutationFn: (body) =>
      api("/graph/explore", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useCodeSnippet(uid: string | null) {
  return useQuery<CodeSnippetResponse>({
    queryKey: ["code-snippet", uid],
    queryFn: () => api(`/code/${encodeURIComponent(uid!)}`, { method: "GET" }),
    enabled: !!uid,
  });
}

export function useBackfillFqn() {
  const qc = useQueryClient();
  return useMutation<{ updated: number; total_checked: number }, Error, void>({
    mutationFn: () => api("/admin/backfill-fqn", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useDeleteRepository() {
  const qc = useQueryClient();
  return useMutation<{ repository: string; deleted_nodes: number }, Error, string>({
    mutationFn: (repo) =>
      api(`/index/${encodeURIComponent(repo)}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["repositories"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useBusinesses() {
  return useQuery<BusinessesResponse>({
    queryKey: ["businesses"],
    queryFn: () => api("/businesses", { method: "GET" }),
    staleTime: 60_000,
  });
}

export function useCreateBusiness() {
  const qc = useQueryClient();
  return useMutation<
    Business,
    Error,
    { id: string; name: string; description: string }
  >({
    mutationFn: (body) =>
      api("/businesses", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["businesses"] });
    },
  });
}

export function useDeleteBusiness() {
  const qc = useQueryClient();
  return useMutation<{ deleted: string }, Error, string>({
    mutationFn: (id) =>
      api(`/businesses/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["businesses"] });
    },
  });
}
