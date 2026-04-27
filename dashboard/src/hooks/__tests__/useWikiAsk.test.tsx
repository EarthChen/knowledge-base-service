import type { ReactNode } from "react";
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as client from "../../api/client";
import { TestI18nProvider } from "../../i18n/context";
import { useWikiAsk } from "../useWikiAsk";

const wrapper = ({ children }: { children: ReactNode }) => (
  <TestI18nProvider locale="en">{children}</TestI18nProvider>
);

describe("useWikiAsk", () => {
  beforeEach(() => {
    vi.spyOn(client, "authHeaders").mockReturnValue({
      "Content-Type": "application/json",
      Authorization: "Bearer test-token",
    });
    globalThis.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses shared authHeaders from client when starting ask", async () => {
    const { result } = renderHook(() => useWikiAsk("my-repo"), { wrapper });

    await act(async () => {
      void result.current.ask({ question: "hello" });
    });

    expect(client.authHeaders).toHaveBeenCalled();
    expect(globalThis.fetch).toHaveBeenCalled();
    const init = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        Authorization: "Bearer test-token",
      }),
    );
  });

  it("aborts the in-flight request on unmount", async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");

    const { result, unmount } = renderHook(() => useWikiAsk("my-repo"), { wrapper });

    await act(async () => {
      void result.current.ask({ question: "q" });
    });

    unmount();
    expect(abortSpy).toHaveBeenCalled();
  });

  it("aborts a previous in-flight request when a new ask starts", async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, "abort");
    const { result } = renderHook(() => useWikiAsk("my-repo"), { wrapper });

    await act(async () => {
      void result.current.ask({ question: "first" });
    });
    await act(async () => {
      void result.current.ask({ question: "second" });
    });

    expect(abortSpy).toHaveBeenCalled();
  });
});
