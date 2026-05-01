import type { ReactNode } from "react";
import { createElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiAnnotations } from "../useWikiAnnotations";
import { api } from "../../api/client";
import type { WikiAnnotation } from "../wikiTypes";

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return { ...mod, api: vi.fn() };
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  }
  Provider.displayName = "TestWikiAnnotationsWrapper";
  return Provider;
}

describe("useWikiAnnotations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches annotations list when business and pageUid are set", async () => {
    const rows: WikiAnnotation[] = [];
    vi.mocked(api).mockResolvedValue(rows);

    const { result } = renderHook(() => useWikiAnnotations("biz", "page-uid"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
    expect(vi.mocked(api)).toHaveBeenCalledWith(`/wiki/pages/${encodeURIComponent("page-uid")}/annotations`);
  });

  it("normalizes non-array API response to empty list", async () => {
    vi.mocked(api).mockResolvedValue({ notAnArray: true });

    const { result } = renderHook(() => useWikiAnnotations("biz", "p2"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("create mutation POSTs body and invalidates query", async () => {
    const created: WikiAnnotation = {
      annotation_id: "a1",
      page_uid: "p",
      text_range_start: 0,
      text_range_end: 3,
      comment: "note",
      author: "tester",
      created_at: "2026-01-01",
    };

    vi.mocked(api).mockResolvedValueOnce([]).mockResolvedValueOnce(created).mockResolvedValueOnce([created]);

    const { result } = renderHook(() => useWikiAnnotations("biz", "p"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await act(async () => {
      await result.current.create.mutateAsync({
        text_range_start: 0,
        text_range_end: 3,
        comment: "note",
        author: "tester",
      });
    });

    const calls = vi.mocked(api).mock.calls;
    const postCall = calls.find((c) => c[1]?.method === "POST");
    expect(postCall?.[0]).toBe(`/wiki/pages/${encodeURIComponent("p")}/annotations`);
    expect(postCall?.[1]).toEqual({
      method: "POST",
      body: JSON.stringify({
        text_range_start: 0,
        text_range_end: 3,
        comment: "note",
        author: "tester",
      }),
    });

    await waitFor(() => expect(result.current.data?.length).toBe(1));
    expect(result.current.data?.[0]).toEqual(created);
  });

  it("remove mutation DELETEs and invalidates query", async () => {
    const ann: WikiAnnotation = {
      annotation_id: "x1",
      page_uid: "p",
      text_range_start: 0,
      text_range_end: 1,
      comment: "c",
      author: "a",
      created_at: "t",
    };
    vi.mocked(api).mockResolvedValueOnce([ann]).mockResolvedValueOnce(undefined).mockResolvedValueOnce([]);

    const { result } = renderHook(() => useWikiAnnotations("biz", "p"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.data?.length).toBe(1));

    await act(async () => {
      await result.current.remove.mutateAsync("x1");
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith(`/wiki/annotations/${encodeURIComponent("x1")}`, {
      method: "DELETE",
    });
    await waitFor(() => expect(result.current.data?.length).toBe(0));
  });
});
