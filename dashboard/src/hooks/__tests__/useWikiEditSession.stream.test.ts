import { type ReactNode, createElement } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiEditSession } from "../useWikiEditSession";
import { api, API_BASE } from "../../api/client";

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return {
    ...mod,
    api: vi.fn(),
    authHeaders: () => ({ "Content-Type": "application/json" }),
  };
});

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useWikiEditSession extended", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sendMessage posts follow-up prompt", async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({ session_id: "sess-1" })
      .mockResolvedValueOnce(undefined);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );

    const { result } = renderHook(() => useWikiEditSession("page-2"), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.createSession("first", "# A");
    });

    await act(async () => {
      await result.current.sendMessage("second prompt");
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      "/wiki/pages/page-2/edit-session/sess-1/message",
      expect.objectContaining({ method: "POST" }),
    );

    fetchMock.mockRestore();
  });

  it("applyEdit posts apply endpoint", async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({ session_id: "sess-2" })
      .mockResolvedValueOnce({ page_uid: "page-3", content: "# Updated" });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );

    const { result } = renderHook(() => useWikiEditSession("page-3"), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.createSession("edit", "# Old");
    });

    let applied: { content: string } | null = null;
    await act(async () => {
      applied = await result.current.applyEdit();
    });

    expect(applied).toEqual({ page_uid: "page-3", content: "# Updated" });
    fetchMock.mockRestore();
  });

  it("streams edited content from SSE", async () => {
    vi.mocked(api).mockResolvedValue({ session_id: "sess-stream" });
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('data: {"type":"content","text":"# Revised"}\n\ndata: {"type":"done"}\n\n'),
        );
        controller.close();
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );

    const { result } = renderHook(() => useWikiEditSession("page-stream"), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.createSession("revise", "# Original");
    });

    await waitFor(() => expect(result.current.editedContent).toBe("# Revised"));
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `${API_BASE}/wiki/pages/page-stream/edit-session/sess-stream/stream`,
      expect.objectContaining({ method: "GET" }),
    );
  });
});
