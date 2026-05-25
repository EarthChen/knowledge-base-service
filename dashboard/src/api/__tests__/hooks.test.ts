import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useHealth,
  useStats,
  useP2Stats,
  useHealthStats,
  useRepositories,
  useHybridSearch,
  useHybridQuickSearch,
  useDeepSearch,
  useWebhookConfig,
  useUpdateWebhookConfig,
  useAnalyzeImpact,
  useFetchPrFiles,
  useIndex,
  useIndexFiles,
  useEnrich,
  useIndexTasks,
  useIndexTask,
  useGraphExplore,
  useGraphExpand,
  useBlastRadius,
  useGraphCommunities,
  useCodeSnippet,
  useBackfillFqn,
  useDeleteRepository,
  useDocuments,
  useDocument,
  useSyncSchedules,
  useCreateSyncSchedule,
  useDeleteSyncSchedule,
  useTriggerSync,
  useArchitectureSearch,
  useFileTree,
  useFileContent,
  useFileEntities,
} from "../hooks";
import { api, triggerEnrich, getCurrentBusiness } from "../client";

vi.mock("../client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../client")>();
  return {
    ...mod,
    api: vi.fn(),
    triggerEnrich: vi.fn(),
    getCurrentBusiness: vi.fn(() => "default"),
  };
});

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("api hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("useHealth fetches /health", async () => {
    vi.mocked(api).mockResolvedValue({ status: "ok" });
    const { result } = renderHook(() => useHealth(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/health", { method: "GET" });
  });

  it("useStats encodes repository query param", async () => {
    vi.mocked(api).mockResolvedValue({ total_nodes: 1 });
    const { result } = renderHook(() => useStats("my/repo"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/stats?repository=my%2Frepo", { method: "GET" });
  });

  it("useP2Stats fetches /stats/p2", async () => {
    vi.mocked(api).mockResolvedValue({ architecture_layers: {} });
    const { result } = renderHook(() => useP2Stats(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/stats/p2", { method: "GET" });
  });

  it("useHealthStats fetches /stats/health", async () => {
    vi.mocked(api).mockResolvedValue({ total_nodes: 1 });
    const { result } = renderHook(() => useHealthStats(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/stats/health", { method: "GET" });
  });

  it("useRepositories fetches /repositories", async () => {
    vi.mocked(api).mockResolvedValue({ repositories: [] });
    const { result } = renderHook(() => useRepositories(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/repositories", { method: "GET" });
  });

  it("useHybridSearch posts hybrid payload with repositories", async () => {
    vi.mocked(api).mockResolvedValue({ semantic_matches: [], total: 0 });
    const { result } = renderHook(() => useHybridSearch(), { wrapper: createWrapper() });
    await result.current.mutateAsync({
      query: "foo",
      k: 5,
      expand_depth: 2,
      repositories: ["a", "b"],
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      "/hybrid",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"repositories":["a","b"]'),
      }),
    );
  });

  it("useHybridQuickSearch is idle when query is too short", () => {
    const { result } = renderHook(() => useHybridQuickSearch("a", true), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("useHybridQuickSearch fetches when enabled with long query", async () => {
    vi.mocked(api).mockResolvedValue({ semantic_matches: [], total: 0 });
    const { result } = renderHook(() => useHybridQuickSearch("hello", true), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/hybrid", expect.objectContaining({ method: "POST" }));
  });

  it("useDeepSearch posts to /deep-search", async () => {
    vi.mocked(api).mockResolvedValue({ answer: "ok" });
    const { result } = renderHook(() => useDeepSearch(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ query: "q", max_iterations: 2, include_code: true });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/deep-search", expect.objectContaining({ method: "POST" }));
  });

  it("useWebhookConfig respects enabled flag", () => {
    const { result } = renderHook(() => useWebhookConfig({ enabled: false }), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("useUpdateWebhookConfig PUTs webhook config", async () => {
    vi.mocked(api).mockResolvedValue({ enabled: true });
    const { result } = renderHook(() => useUpdateWebhookConfig(), { wrapper: createWrapper() });
    await result.current.mutateAsync({
      enabled: true,
      debounce_seconds: 60,
      auto_update_branches: [],
      providers: {},
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/hooks/config", expect.objectContaining({ method: "PUT" }));
  });

  it("useAnalyzeImpact posts changed files", async () => {
    vi.mocked(api).mockResolvedValue({ affected_pages: [] });
    const { result } = renderHook(() => useAnalyzeImpact(), { wrapper: createWrapper() });
    await result.current.mutateAsync({
      repository: "demo",
      changed_files: [{ path: "a.ts", status: "modified" }],
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/demo/analyze-impact", expect.objectContaining({ method: "POST" }));
  });

  it("useFetchPrFiles posts PR url", async () => {
    vi.mocked(api).mockResolvedValue({ changed_files: [] });
    const { result } = renderHook(() => useFetchPrFiles(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ url: "https://github.com/o/r/pull/1" });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/pr/fetch", expect.objectContaining({ method: "POST" }));
  });

  it("useIndex posts index body", async () => {
    vi.mocked(api).mockResolvedValue({ task_id: "t1" });
    const { result } = renderHook(() => useIndex(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ directory: "/tmp" });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/index", expect.objectContaining({ method: "POST" }));
  });

  it("useIndexFiles posts files payload", async () => {
    vi.mocked(api).mockResolvedValue({ task_id: "t2" });
    const { result } = renderHook(() => useIndexFiles(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ files: [{ path: "a.py", content: "x" }] });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/index/files", expect.objectContaining({ method: "POST" }));
  });

  it("useEnrich delegates to triggerEnrich", async () => {
    vi.mocked(triggerEnrich).mockResolvedValue({ task_id: "e1" });
    const { result } = renderHook(() => useEnrich(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ repository: "demo", force: false });
    expect(vi.mocked(getCurrentBusiness)).toHaveBeenCalled();
    expect(vi.mocked(triggerEnrich)).toHaveBeenCalledWith("default", { repository: "demo", force: false });
  });

  it("useIndexTasks fetches task list", async () => {
    vi.mocked(api).mockResolvedValue({ tasks: [] });
    const { result } = renderHook(() => useIndexTasks(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/index/tasks", { method: "GET" });
  });

  it("useIndexTask fetches single task when id set", async () => {
    vi.mocked(api).mockResolvedValue({ task_id: "abc", status: "running" });
    const { result } = renderHook(() => useIndexTask("abc"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/index/tasks/abc", { method: "GET" });
  });

  it("useGraphExplore posts explore request", async () => {
    vi.mocked(api).mockResolvedValue({ nodes: [], edges: [] });
    const { result } = renderHook(() => useGraphExplore(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ name: "main", depth: 2, limit: 50 });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/graph/explore", expect.objectContaining({ method: "POST" }));
  });

  it("useGraphExpand posts expand request", async () => {
    vi.mocked(api).mockResolvedValue({ nodes: [], edges: [] });
    const { result } = renderHook(() => useGraphExpand(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ node_id: "n1", depth: 1, limit: 20 });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/graph/expand", expect.objectContaining({ method: "POST" }));
  });

  it("useBlastRadius posts blast payload", async () => {
    vi.mocked(api).mockResolvedValue({ affected: [] });
    const { result } = renderHook(() => useBlastRadius(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ entity_names: ["Foo"], max_depth: 2, repository: "demo" });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/graph/blast-radius", expect.objectContaining({ method: "POST" }));
  });

  it("useGraphCommunities GETs with query params", async () => {
    vi.mocked(api).mockResolvedValue({ communities: [] });
    const { result } = renderHook(() => useGraphCommunities(), { wrapper: createWrapper() });
    await result.current.mutateAsync({ repository: "demo", min_size: 3 });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/graph/communities?repository=demo&min_size=3", { method: "GET" });
  });

  it("useCodeSnippet fetches code by uid", async () => {
    vi.mocked(api).mockResolvedValue({ name: "fn", file: "a.ts", content: "x" });
    const { result } = renderHook(() => useCodeSnippet("uid-1"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/code/uid-1", { method: "GET" });
  });

  it("useBackfillFqn posts admin endpoint", async () => {
    vi.mocked(api).mockResolvedValue({ updated: 1, total_checked: 1 });
    const { result } = renderHook(() => useBackfillFqn(), { wrapper: createWrapper() });
    await result.current.mutateAsync();
    expect(vi.mocked(api)).toHaveBeenCalledWith("/admin/backfill-fqn", { method: "POST" });
  });

  it("useDeleteRepository deletes repo index", async () => {
    vi.mocked(api).mockResolvedValue({ repository: "demo", deleted_nodes: 3 });
    const { result } = renderHook(() => useDeleteRepository(), { wrapper: createWrapper() });
    await result.current.mutateAsync("demo");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/index/demo", { method: "DELETE" });
  });

  it("useDocuments fetches document list", async () => {
    vi.mocked(api).mockResolvedValue({ documents: [] });
    const { result } = renderHook(() => useDocuments("demo"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/documents?repository=demo", { method: "GET" });
  });

  it("useDocument fetches document detail", async () => {
    vi.mocked(api).mockResolvedValue({ uid: "d1", title: "Doc" });
    const { result } = renderHook(() => useDocument("d1"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/documents/d1", { method: "GET" });
  });

  it("useSyncSchedules fetches schedules", async () => {
    vi.mocked(api).mockResolvedValue({ schedules: [] });
    const { result } = renderHook(() => useSyncSchedules(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/sync/schedules", { method: "GET" });
  });

  it("useCreateSyncSchedule posts schedule", async () => {
    vi.mocked(api).mockResolvedValue({ repository: "demo", enabled: true });
    const { result } = renderHook(() => useCreateSyncSchedule(), { wrapper: createWrapper() });
    await result.current.mutateAsync({
      repository: "demo",
      git_url: "",
      branch: "main",
      interval_minutes: 60,
      enabled: true,
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/sync/schedules", expect.objectContaining({ method: "POST" }));
  });

  it("useDeleteSyncSchedule deletes encoded path", async () => {
    vi.mocked(api).mockResolvedValue({ deleted: "org/demo" });
    const { result } = renderHook(() => useDeleteSyncSchedule(), { wrapper: createWrapper() });
    await result.current.mutateAsync("org/demo");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/sync/schedules/org/demo", { method: "DELETE" });
  });

  it("useTriggerSync triggers sync", async () => {
    vi.mocked(api).mockResolvedValue({ ok: true });
    const { result } = renderHook(() => useTriggerSync(), { wrapper: createWrapper() });
    await result.current.mutateAsync("org/demo");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/sync/schedules/org/demo/trigger", { method: "POST" });
  });

  it("useArchitectureSearch builds query string", async () => {
    vi.mocked(api).mockResolvedValue({ classes: [], total: 0, total_count: 0, layer: "domain" });
    const { result } = renderHook(
      () => useArchitectureSearch("domain", { repository: "demo", search: "User", offset: 0, limit: 10 }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      "/search/architecture?layer=domain&repository=demo&search=User&offset=0&limit=10",
      { method: "GET" },
    );
  });

  it("useFileTree fetches tree for repository", async () => {
    vi.mocked(api).mockResolvedValue({ type: "dir", name: "root", path: "", children: [] });
    const { result } = renderHook(() => useFileTree("demo"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/files/tree?repository=demo", { method: "GET" });
  });

  it("useFileContent fetches file content", async () => {
    vi.mocked(api).mockResolvedValue({ content: "x", start_line: 1 });
    const { result } = renderHook(() => useFileContent("demo", "main.py"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      "/files/content?repository=demo&file_path=main.py",
      { method: "GET" },
    );
  });

  it("useFileEntities fetches entities for path", async () => {
    vi.mocked(api).mockResolvedValue({ entities: [] });
    const { result } = renderHook(() => useFileEntities("src/main.py"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/files/entities?file_path=src%2Fmain.py", { method: "GET" });
  });
});
