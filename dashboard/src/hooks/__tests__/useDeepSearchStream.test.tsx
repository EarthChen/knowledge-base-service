import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useDeepSearchStream } from "../useDeepSearchStream";
import { TestI18nProvider } from "../../i18n/context";
import type { ReactNode } from "react";

vi.mock("../../api/client", () => ({
  API_BASE: "http://test",
  authHeaders: () => ({ Authorization: "Bearer test" }),
}));

function wrapper({ children }: { children: ReactNode }) {
  return <TestI18nProvider>{children}</TestI18nProvider>;
}

function sseBody(events: Array<{ event: string; data: object }>): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const chunks = events.map(
    (e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`,
  );
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i++]));
      } else {
        controller.close();
      }
    },
  });
}

describe("useDeepSearchStream", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        body: sseBody([{ event: "plan", data: { step: 1 } }]),
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ignores stale stream updates after a newer start()", async () => {
    let firstPull: (() => void) | undefined;
    const firstStream = new ReadableStream<Uint8Array>({
      start(controller) {
        firstPull = () => controller.enqueue(new TextEncoder().encode("event: plan\ndata: {\"stale\":true}\n\n"));
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce({ ok: true, body: firstStream } as Response)
      .mockResolvedValueOnce({
        ok: true,
        body: sseBody([{ event: "plan", data: { fresh: true } }]),
      } as Response);

    const { result } = renderHook(() => useDeepSearchStream(), { wrapper });

    await act(async () => {
      void result.current.start({ query: "first" });
    });

    await act(async () => {
      void result.current.start({ query: "second" });
    });

    firstPull?.();

    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    const lastStage = result.current.stages[result.current.stages.length - 1];
    expect(lastStage?.data).toEqual({ fresh: true });
    expect(lastStage?.data).not.toEqual({ stale: true });
  });
});
