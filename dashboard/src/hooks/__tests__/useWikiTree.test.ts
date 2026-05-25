import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiTree } from "../useWikiTree";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useWikiTree", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches wiki tree with business id and view type", async () => {
    const payload = { tree: [{ title: "Root", path: "/", children: [] }] };
    vi.mocked(api).mockResolvedValue(payload);

    const { result } = renderHook(() => useWikiTree("my-biz", "business"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/tree?business_id=${encodeURIComponent("my-biz")}&view=${encodeURIComponent("business")}`,
    );
    expect(result.current.data).toEqual(payload);
  });

  it("includes wiki_tier when tier is set", async () => {
    vi.mocked(api).mockResolvedValue({ tree: [] });

    const { result } = renderHook(() => useWikiTree("b1", "code", "standard"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/tree?business_id=${encodeURIComponent("b1")}&view=${encodeURIComponent("code")}&wiki_tier=standard`,
    );
  });

  it("does not fetch when business id is empty", () => {
    const { result } = renderHook(() => useWikiTree("", "business"), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
});
