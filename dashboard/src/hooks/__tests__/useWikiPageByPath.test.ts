import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiPageByPath } from "../useWikiPageByPath";
import { api } from "../../api/client";
import type { WikiPageDetail } from "../wikiTypes";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

const detail: WikiPageDetail = {
  path: "/a",
  title: "A",
  content: "",
  diagrams: [],
  source_locations: [],
  method_locations: [],
  context: {},
};

describe("useWikiPageByPath", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches by path with encoded query params and trims the path", async () => {
    vi.mocked(api).mockResolvedValue(detail);
    const { result } = renderHook(
      () => useWikiPageByPath("b1", "  /p/a  "),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/pages/by-path?business_id=${encodeURIComponent("b1")}&path=${encodeURIComponent("/p/a")}`,
    );
  });

  it("stays disabled when user passes enabled: false", () => {
    const { result } = renderHook(
      () => useWikiPageByPath("b1", "/x", { enabled: false }),
      { wrapper: createWrapper() },
    );
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("does not run without business or path", () => {
    const { result: noPath } = renderHook(() => useWikiPageByPath("b", undefined), {
      wrapper: createWrapper(),
    });
    expect(noPath.current.fetchStatus).toBe("idle");
    const { result: noBiz } = renderHook(() => useWikiPageByPath("   ", "/a"), { wrapper: createWrapper() });
    expect(noBiz.current.fetchStatus).toBe("idle");
  });
});
