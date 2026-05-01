import type { ReactNode } from "react";
import { createElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiQualityScore } from "../useWikiQualityScore";
import { api } from "../../api/client";
import type { WikiQualityScoreResponse } from "../wikiTypes";

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
  Provider.displayName = "TestWikiQualityWrapper";
  return Provider;
}

describe("useWikiQualityScore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads quality score for business id", async () => {
    const payload: WikiQualityScoreResponse = {
      score: 0.85,
      factors: [],
      details: {},
    };
    vi.mocked(api).mockResolvedValue(payload);

    const { result } = renderHook(() => useWikiQualityScore("biz-1"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(payload);
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/quality-score?business_id=${encodeURIComponent("biz-1")}`,
    );
  });

  it("does not fetch when business id is empty", async () => {
    const { result } = renderHook(() => useWikiQualityScore(""), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("enters error state when API rejects", async () => {
    vi.mocked(api).mockRejectedValue(new Error("quality down"));

    const { result } = renderHook(() => useWikiQualityScore("b"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("quality down");
  });
});
