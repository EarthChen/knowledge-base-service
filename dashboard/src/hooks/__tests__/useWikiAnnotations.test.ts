import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiAnnotations } from "../useWikiAnnotations";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useWikiAnnotations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches annotations for a wiki page", async () => {
    vi.mocked(api).mockResolvedValue([
      {
        annotation_id: "a1",
        page_uid: "page-1",
        text_range_start: 0,
        text_range_end: 4,
        comment: "note",
        author: "tester",
        created_at: "2026-01-01T00:00:00.000Z",
      },
    ]);
    const { result } = renderHook(() => useWikiAnnotations("default", "page-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });

  it("creates and deletes annotations", async () => {
    vi.mocked(api).mockResolvedValueOnce([]).mockResolvedValueOnce({ annotation_id: "a2" });
    const { result } = renderHook(() => useWikiAnnotations("default", "page-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await result.current.create.mutateAsync({
      text_range_start: 0,
      text_range_end: 3,
      comment: "hi",
      author: "tester",
    });
    vi.mocked(api).mockResolvedValueOnce(undefined);
    await result.current.remove.mutateAsync("a2");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/annotations/a2", { method: "DELETE" });
  });

  it("returns empty list when API response is not an array", async () => {
    vi.mocked(api).mockResolvedValue({ unexpected: true });
    const { result } = renderHook(() => useWikiAnnotations("default", "page-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("does not fetch when page uid is empty", () => {
    const { result } = renderHook(() => useWikiAnnotations("default", ""), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
});
