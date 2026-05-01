import type { ReactNode } from "react";
import { createElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiNavigation, type NavigationContext } from "../useWikiNavigation";
import { api } from "../../api/client";

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return { ...mod, api: vi.fn() };
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  }
  Provider.displayName = "TestWikiNavigationWrapper";
  return Provider;
}

describe("useWikiNavigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls API with encoded repo and path when repository contains a slash", async () => {
    const payload: NavigationContext = {
      parent_path: null,
      parent_title: null,
      sibling_paths: [],
      child_paths: [],
      related_flow_paths: [],
      breadcrumbs: [],
    };
    vi.mocked(api).mockResolvedValue(payload);

    const { result } = renderHook(() => useWikiNavigation("org/wiki-repo", "/topics/a/page"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(payload);
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/navigation/by-path?repository=${encodeURIComponent("org/wiki-repo")}&path=${encodeURIComponent("/topics/a/page")}`,
    );
  });

  it("does not fetch when repository has no slash (disabled query)", async () => {
    const { result } = renderHook(() => useWikiNavigation("wiki-repo-only", "/p"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("enters error state when API rejects", async () => {
    vi.mocked(api).mockRejectedValue(new Error("nav failed"));

    const { result } = renderHook(() => useWikiNavigation("a/b", "/c"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("nav failed");
  });
});
