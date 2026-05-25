import { type ReactNode, createElement } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiEditSession } from "../useWikiEditSession";
import { api } from "../../api/client";

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

describe("useWikiEditSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates edit session and calls POST with page uid", async () => {
    vi.mocked(api).mockResolvedValue({ session_id: "sess-1" });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );

    const { result } = renderHook(() => useWikiEditSession("page-uid-1"), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.createSession("improve intro", "# Hello");
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/pages/page-uid-1/edit-session", {
      method: "POST",
      body: JSON.stringify({ prompt: "improve intro", current_content: "# Hello" }),
    });
    expect(result.current.sessionId).toBe("sess-1");

    fetchMock.mockRestore();
  });

  it("discards session without API when no session id", async () => {
    const { result } = renderHook(() => useWikiEditSession("page-uid-2"), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.discardSession();
    });

    expect(vi.mocked(api)).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.sessionId).toBeNull();
      expect(result.current.events).toEqual([]);
    });
  });
});
