import type { ReactNode } from "react";
import { createElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, api } from "../../api/client";
import { useWikiDomainTree, type TopicTreeNode } from "../useWikiDomainTree";

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return { ...mod, api: vi.fn() };
});

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useWikiDomainTree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches domain tree from GET /wiki/domain-tree with encoded business id", async () => {
    const payload = {
      tree: [
        {
          name: "Auth",
          page_type: "domain",
          path: "/auth",
          children: [],
          module_count: 2,
        } satisfies TopicTreeNode,
      ],
      review_status: { "/auth": "approved" },
    };
    vi.mocked(api).mockResolvedValue(payload);

    const { result } = renderHook(() => useWikiDomainTree("my-biz"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(vi.mocked(api)).toHaveBeenCalledWith(`/wiki/domain-tree?business_id=${encodeURIComponent("my-biz")}`);
    expect(result.current.data).toEqual(payload);
    expect(result.current.data?.tree[0]?.module_count).toBe(2);
  });

  it("starts in loading state then resolves", async () => {
    let resolve!: (v: unknown) => void;
    const deferred = new Promise((r) => {
      resolve = r;
    });
    vi.mocked(api).mockReturnValue(deferred as Promise<unknown>);

    const { result } = renderHook(() => useWikiDomainTree("b1"), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);

    resolve({ tree: [], review_status: {} });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.tree).toEqual([]);
  });

  it("surfaces error state when API fails", async () => {
    vi.mocked(api).mockRejectedValue(new ApiError("not found", 404, null));

    const { result } = renderHook(() => useWikiDomainTree("bad"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("not found");
  });

  it("does not fetch when business id is empty", () => {
    const { result } = renderHook(() => useWikiDomainTree(""), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
});
