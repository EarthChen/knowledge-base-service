import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useWikiEvents } from "../useWikiEvents";

describe("useWikiEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts disconnected when disabled", () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() => useWikiEvents("default", onEvent, false));
    expect(result.current.connectionStatus).toBe("disconnected");
  });

  it("connects and forwards wiki events from SSE stream", async () => {
    const onEvent = vi.fn();
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('data: {"type":"page_updated","path":"/auth","business_id":"default"}\n\n'),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: stream,
      }),
    );

    renderHook(() => useWikiEvents("default", onEvent, true));
    await waitFor(() => expect(onEvent).toHaveBeenCalled());
    expect(onEvent.mock.calls[0][0]).toMatchObject({ type: "page_updated", path: "/auth" });
  });
});
