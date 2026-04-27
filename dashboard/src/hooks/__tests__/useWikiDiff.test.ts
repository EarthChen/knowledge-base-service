import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiDiff } from "../useWikiDiff";
import { api } from "../../api/client";
import type { WikiDiff } from "../wikiTypes";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

const sample: WikiDiff = {
  from_version: 1,
  to_version: 2,
  hunks: [],
};

describe("useWikiDiff", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches diff when enabled and encodes the page path", async () => {
    vi.mocked(api).mockResolvedValue(sample);
    const { result } = renderHook(() => useWikiDiff("b1", "docs/a%2Fb", 1, 2), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(sample);
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/pages/${encodeURIComponent("docs/a%2Fb")}/diff?from=1&to=2`,
    );
  });

  it("does not run the query when from and to versions are equal", () => {
    const { result } = renderHook(() => useWikiDiff("b1", "p1", 2, 2), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("is disabled for empty business id or non-positive versions", () => {
    const { result: emptyBiz } = renderHook(() => useWikiDiff("   ", "p1", 1, 2), {
      wrapper: createWrapper(),
    });
    expect(emptyBiz.current.fetchStatus).toBe("idle");
    const { result: badVer } = renderHook(() => useWikiDiff("b", "p1", 0, 1), { wrapper: createWrapper() });
    expect(badVer.current.fetchStatus).toBe("idle");
  });
});
