import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useWikiAsk } from "../useWikiAsk";
import { TestI18nProvider } from "../../i18n/context";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return <TestI18nProvider>{children}</TestI18nProvider>;
}

function sseResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  const stream = new ReadableStream({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(chunks[i]));
      i += 1;
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("useWikiAsk", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("streams tokens and completes with sources", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"token","content":"Hello"}\n\n',
        'data: {"type":"sources","sources":[{"entity":"Doc","file_path":"doc.md","start_line":1,"wiki_page":"/doc","relevance_score":0.9}]}\n\n',
        'data: {"type":"done","conversation_id":"conv-1","tokens_used":3,"reasoning_path":null}\n\n',
      ]),
    );

    const { result } = renderHook(() => useWikiAsk("demo-repo"), { wrapper });

    await act(async () => {
      await result.current.ask({ repository: "demo-repo", question: "What is this?" });
    });

    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    expect(result.current.answer).toBe("Hello");
    expect(result.current.sources).toHaveLength(1);
    expect(result.current.conversationId).toBe("conv-1");
  });

  it("sets error when response is not ok", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("bad", { status: 500 }));
    const { result } = renderHook(() => useWikiAsk("demo-repo"), { wrapper });

    await act(async () => {
      await result.current.ask({ repository: "demo-repo", question: "fail?" });
    });

    await waitFor(() => expect(result.current.error).toBeTruthy());
  });

  it("reset clears state", async () => {
    const { result } = renderHook(() => useWikiAsk("demo-repo"), { wrapper });
    act(() => {
      result.current.setAnswer("partial");
    });
    act(() => {
      result.current.reset();
    });
    expect(result.current.answer).toBe("");
    expect(result.current.error).toBeNull();
  });
});
