import type { ReactNode } from "react";
import { createElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../../api/client";
import { TestI18nProvider } from "../../i18n/context";
import { useWikiIncremental } from "../useWikiIncremental";

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return { ...mod, api: vi.fn() };
});

function createSuite() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(TestI18nProvider, { locale: "en" }, children),
    );
  }
  return { queryClient, Wrapper };
}

describe("useWikiIncremental", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockResolvedValue({ task_id: "task-xyz" });
  });

  it("POSTs trimmed repository with language en when locale is en", async () => {
    const { Wrapper } = createSuite();
    const { result } = renderHook(() => useWikiIncremental("  my/repo  "), { wrapper: Wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/generate-incremental", {
      method: "POST",
      body: JSON.stringify({ repository: "my/repo", language: "en" }),
    });
  });

  it("uses language zh when locale is zh", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    function WrapperZh({ children }: { children: ReactNode }) {
      return createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(TestI18nProvider, { locale: "zh" }, children),
      );
    }

    const { result } = renderHook(() => useWikiIncremental("repo"), { wrapper: WrapperZh });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/generate-incremental", {
      method: "POST",
      body: JSON.stringify({ repository: "repo", language: "zh" }),
    });
  });

  it("invalidates wiki queries on success", async () => {
    const { queryClient, Wrapper } = createSuite();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useWikiIncremental("r1"), { wrapper: Wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["wiki"] });
    invalidateSpy.mockRestore();
  });
});
