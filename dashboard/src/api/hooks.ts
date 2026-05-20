import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { STALE_TIME } from "./cacheConfig";
import { api, ApiError, getCurrentBusiness, triggerEnrich } from "./client";
import { queryKeys, type ArchitectureSearchQueryOptions } from "./queryKeys";
import type {
  GraphStats,
  RepositoriesResponse,
  HybridSearchParams,
  HybridSearchResponse,
  HealthResponse,
  IndexResponse,
  IndexTask,
  IndexTasksResponse,
  GraphExploreResponse,
  GraphExpandRequest,
  GraphExpandResponse,
  BlastRadiusResponse,
  CommunitiesResponse,
  CodeSnippetResponse,
  DocumentsResponse,
  DocumentDetail,
  DeepSearchResponse,
  EnrichRequest,
  TaskInfo,
  SyncSchedule,
  SyncSchedulesResponse,
  SyncScheduleRequest,
  P2Stats,
  KnowledgeHealthStats,
  ArchitectureSearchResponse,
  WebhookConfig,
  AnalyzeImpactResponse,
  AnalyzeImpactFile,
  FetchPrFilesResponse,
  FileTreeNode,
  FileContentResponse,
  FileEntitiesResponse,
} from "./types";

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: queryKeys.health,
    queryFn: () => api("/health", { method: "GET" }),
    refetchInterval: 30_000,
  });
}

export function useStats(repository?: string) {
  const params = repository ? `?repository=${encodeURIComponent(repository)}` : "";
  return useQuery<GraphStats>({
    queryKey: queryKeys.stats(repository),
    queryFn: () => api(`/stats${params}`, { method: "GET" }),
    staleTime: STALE_TIME.NORMAL,
  });
}

export function useP2Stats() {
  return useQuery<P2Stats>({
    queryKey: queryKeys.p2Stats,
    queryFn: () => api("/stats/p2", { method: "GET" }),
    staleTime: STALE_TIME.NORMAL,
  });
}

export function useHealthStats() {
  return useQuery<KnowledgeHealthStats>({
    queryKey: queryKeys.healthStats,
    queryFn: () => api("/stats/health", { method: "GET" }),
    staleTime: 60_000,
    retry: 1,
  });
}

export function useRepositories() {
  return useQuery<RepositoriesResponse>({
    queryKey: queryKeys.repositories,
    queryFn: () => api("/repositories", { method: "GET" }),
  });
}

export function useHybridSearch() {
  return useMutation<
    HybridSearchResponse,
    ApiError,
    HybridSearchParams
  >({
    mutationFn: (body) => {
      const payload: Record<string, unknown> = {
        query: body.query,
        k: body.k,
        expand_depth: body.expand_depth,
      };
      if (body.entity_type) payload.entity_type = body.entity_type;
      if (body.language) payload.language = body.language;
      if (body.offset !== undefined) payload.offset = body.offset;
      if (body.limit !== undefined) payload.limit = body.limit;
      if (body.sort_by) payload.sort_by = body.sort_by;
      if (body.repositories != null && body.repositories.length > 0) {
        payload.repositories = body.repositories;
      } else if (body.repository) {
        payload.repository = body.repository;
      }
      return api("/hybrid", { method: "POST", body: JSON.stringify(payload) });
    },
  });
}

/** Debounced callers should gate `enabled`; used by the command palette quick search. */
export function useHybridQuickSearch(query: string, enabled: boolean) {
  const trimmed = query.trim();
  return useQuery<HybridSearchResponse>({
    queryKey: queryKeys.hybridQuick(trimmed),
    queryFn: () =>
      api("/hybrid", {
        method: "POST",
        body: JSON.stringify({
          query: trimmed,
          k: 12,
          expand_depth: 2,
          offset: 0,
          limit: 12,
          sort_by: "score",
        }),
      }),
    enabled: enabled && trimmed.length >= 2,
  });
}

export function useDeepSearch() {
  return useMutation<
    DeepSearchResponse,
    ApiError,
    { query: string; max_iterations: number; include_code: boolean }
  >({
    mutationFn: (body) =>
      api("/deep-search", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useWebhookConfig(options?: { enabled?: boolean }) {
  return useQuery<WebhookConfig>({
    queryKey: queryKeys.webhookConfig,
    queryFn: () => api("/hooks/config", { method: "GET" }),
    staleTime: 60_000,
    enabled: options?.enabled ?? true,
  });
}

export function useUpdateWebhookConfig() {
  const qc = useQueryClient();
  return useMutation<WebhookConfig, ApiError, WebhookConfig>({
    mutationFn: (body) =>
      api("/hooks/config", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.webhookConfig });
    },
  });
}

export function useAnalyzeImpact() {
  return useMutation<
    AnalyzeImpactResponse,
    ApiError,
    { repository: string; changed_files: AnalyzeImpactFile[] }
  >({
    mutationFn: ({ repository, changed_files }) =>
      api(`/wiki/${encodeURIComponent(repository)}/analyze-impact`, {
        method: "POST",
        body: JSON.stringify({ changed_files }),
      }),
  });
}

export function useFetchPrFiles() {
  return useMutation<FetchPrFilesResponse, ApiError, { url: string }>({
    mutationFn: ({ url }) =>
      api("/pr/fetch", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
  });
}

export function useIndex() {
  return useMutation<IndexResponse, ApiError, Record<string, unknown>>({
    mutationFn: (body) =>
      api("/index", { method: "POST", body: JSON.stringify(body) }),
  });
}

export interface IndexFilesPayload {
  files: { path: string; content: string }[];
  repository?: string;
}

export function useIndexFiles() {
  const qc = useQueryClient();
  return useMutation<IndexResponse, ApiError, IndexFilesPayload>({
    mutationFn: (body) =>
      api("/index/files", {
        method: "POST",
        body: JSON.stringify({
          files: body.files,
          repository: body.repository ?? "uploaded",
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.indexTasks });
    },
  });
}

export function useEnrich() {
  const qc = useQueryClient();
  return useMutation<TaskInfo, ApiError, EnrichRequest>({
    mutationFn: (body) => triggerEnrich(getCurrentBusiness(), body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.indexTasks });
    },
  });
}

export function useIndexTasks() {
  return useQuery<IndexTasksResponse>({
    queryKey: queryKeys.indexTasks,
    queryFn: () => api("/index/tasks", { method: "GET" }),
    refetchInterval: 3000,
  });
}

export function useIndexTask(taskId: string | null) {
  return useQuery<IndexTask>({
    queryKey: queryKeys.indexTask(taskId),
    queryFn: () => api(`/index/tasks/${encodeURIComponent(taskId!)}`, { method: "GET" }),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && (data.status === "completed" || data.status === "failed")) {
        return false;
      }
      return 1000;
    },
  });
}

export function useGraphExplore() {
  return useMutation<
    GraphExploreResponse,
    ApiError,
    { name: string; center_uid?: string; depth: number; limit: number }
  >({
    mutationFn: (body) =>
      api("/graph/explore", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useGraphExpand() {
  return useMutation<GraphExpandResponse, ApiError, GraphExpandRequest>({
    mutationFn: (body) =>
      api("/graph/expand", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useBlastRadius() {
  return useMutation<
    BlastRadiusResponse,
    ApiError,
    { entity_names: string[]; max_depth: number; repository?: string | null }
  >({
    mutationFn: (body) =>
      api("/graph/blast-radius", {
        method: "POST",
        body: JSON.stringify({
          entity_names: body.entity_names,
          max_depth: body.max_depth,
          repository: body.repository ?? null,
        }),
      }),
  });
}

export function useGraphCommunities() {
  return useMutation<
    CommunitiesResponse,
    ApiError,
    { repository?: string | null; min_size?: number }
  >({
    mutationFn: ({ repository, min_size }) => {
      const params = new URLSearchParams();
      if (repository && repository.trim()) params.set("repository", repository.trim());
      if (min_size != null) params.set("min_size", String(min_size));
      const q = params.toString();
      return api(`/graph/communities${q ? `?${q}` : ""}`, { method: "GET" });
    },
  });
}

export function useCodeSnippet(uid: string | null) {
  return useQuery<CodeSnippetResponse>({
    queryKey: queryKeys.codeSnippet(uid),
    queryFn: () => api(`/code/${encodeURIComponent(uid!)}`, { method: "GET" }),
    enabled: !!uid,
  });
}

export function useBackfillFqn() {
  const qc = useQueryClient();
  return useMutation<{ updated: number; total_checked: number }, ApiError, void>({
    mutationFn: () => api("/admin/backfill-fqn", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.statsAll });
    },
  });
}

export function useDeleteRepository() {
  const qc = useQueryClient();
  return useMutation<{ repository: string; deleted_nodes: number }, ApiError, string>({
    mutationFn: (repo) =>
      api(`/index/${encodeURIComponent(repo)}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.repositories });
      qc.invalidateQueries({ queryKey: queryKeys.statsAll });
    },
  });
}

export function useDocuments(repository?: string) {
  const params = repository ? `?repository=${encodeURIComponent(repository)}` : "";
  return useQuery<DocumentsResponse>({
    queryKey: queryKeys.documents(repository),
    queryFn: () => api(`/documents${params}`, { method: "GET" }),
    staleTime: 60_000,
  });
}

export function useDocument(uid: string | null) {
  return useQuery<DocumentDetail>({
    queryKey: queryKeys.document(uid),
    queryFn: () => api(`/documents/${encodeURIComponent(uid!)}`, { method: "GET" }),
    enabled: !!uid,
    staleTime: 60_000,
  });
}

export function useSyncSchedules(options?: { enabled?: boolean }) {
  return useQuery<SyncSchedulesResponse>({
    queryKey: queryKeys.syncSchedules,
    queryFn: () => api("/sync/schedules", { method: "GET" }),
    enabled: options?.enabled ?? true,
  });
}

export function useCreateSyncSchedule() {
  const qc = useQueryClient();
  return useMutation<SyncSchedule, ApiError, SyncScheduleRequest>({
    mutationFn: (body) =>
      api<SyncSchedule>("/sync/schedules", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.syncSchedules });
    },
  });
}

export function useDeleteSyncSchedule() {
  const qc = useQueryClient();
  return useMutation<{ deleted: string }, ApiError, string>({
    mutationFn: (repo) => {
      const path = repo.split("/").map(encodeURIComponent).join("/");
      return api(`/sync/schedules/${path}`, { method: "DELETE" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.syncSchedules });
    },
  });
}

export function useTriggerSync() {
  const qc = useQueryClient();
  return useMutation<Record<string, unknown>, ApiError, string>({
    mutationFn: (repo) => {
      const path = repo.split("/").map(encodeURIComponent).join("/");
      return api(`/sync/schedules/${path}/trigger`, { method: "POST" });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.syncSchedules });
    },
  });
}

export function useArchitectureSearch(layer: string, options: ArchitectureSearchQueryOptions = {}) {
  const params = new URLSearchParams();
  params.set("layer", layer);
  if (options.repository) params.set("repository", options.repository);
  if (options.search) params.set("search", options.search);
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  if (options.limit !== undefined) params.set("limit", String(options.limit));

  return useQuery<ArchitectureSearchResponse>({
    queryKey: queryKeys.architectureSearch(layer, options),
    queryFn: () => api(`/search/architecture?${params.toString()}`, { method: "GET" }),
    enabled: !!layer,
  });
}

export function useFileTree(repository: string) {
  return useQuery<FileTreeNode>({
    queryKey: queryKeys.fileTree(repository),
    queryFn: () =>
      api(`/files/tree?repository=${encodeURIComponent(repository.trim())}`, { method: "GET" }),
    enabled: !!repository.trim(),
    staleTime: 2 * 60 * 1000,
  });
}

export function useFileContent(repository: string, filePath: string, enabled = true) {
  const params = new URLSearchParams();
  params.set("repository", repository);
  params.set("file_path", filePath);
  return useQuery<FileContentResponse>({
    queryKey: queryKeys.fileContent(repository, filePath),
    queryFn: () => api(`/files/content?${params.toString()}`, { method: "GET" }),
    enabled: enabled && !!repository && !!filePath,
    staleTime: 5 * 60 * 1000,
  });
}

export function useFileEntities(filePath: string, enabled = true) {
  return useQuery<FileEntitiesResponse>({
    queryKey: queryKeys.fileEntities(filePath),
    queryFn: () =>
      api(`/files/entities?file_path=${encodeURIComponent(filePath)}`, { method: "GET" }),
    enabled: enabled && !!filePath,
  });
}
