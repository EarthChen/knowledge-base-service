import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import * as apiClient from "../../api/client";
import { useWikiEvents } from "../useWikiEvents";

type MockEsInstance = {
  url: string;
  onmessage: ((e: MessageEvent) => void) | null;
  onerror: ((e: Event) => void) | null;
  onopen: ((e: Event) => void) | null;
  close: ReturnType<typeof vi.fn>;
};

const instances: MockEsInstance[] = [];

function MockEventSource(this: MockEsInstance, url: string) {
  const self = this as MockEsInstance;
  self.url = url;
  self.onmessage = null;
  self.onerror = null;
  self.onopen = null;
  self.close = vi.fn();
  instances.push(self);
}

describe("useWikiEvents", () => {
  beforeEach(() => {
    instances.length = 0;
    vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("connects with business id in url", () => {
    const onEvent = vi.fn();
    const spy = vi.spyOn(apiClient, "getToken").mockReturnValue("");
    renderHook(() => useWikiEvents("biz-1", onEvent));
    expect(instances[0].url).toContain("/api/v1/wiki/events");
    expect(instances[0].url).toContain("business_id=biz-1");
    expect(instances[0].url).not.toContain("token=");
    spy.mockRestore();
  });

  it("appends token query when getToken returns a non-empty value", () => {
    const onEvent = vi.fn();
    const spy = vi.spyOn(apiClient, "getToken").mockReturnValue("secret-tok");
    renderHook(() => useWikiEvents("biz-1", onEvent));
    const u = new URL(instances[0].url, "http://localhost");
    expect(u.searchParams.get("token")).toBe("secret-tok");
    expect(u.searchParams.get("business_id")).toBe("biz-1");
    spy.mockRestore();
  });

  it("omits token param when getToken is empty", () => {
    const onEvent = vi.fn();
    const spy = vi.spyOn(apiClient, "getToken").mockReturnValue("");
    renderHook(() => useWikiEvents("biz-1", onEvent));
    const u = new URL(instances[0].url, "http://localhost");
    expect(u.searchParams.get("token")).toBeNull();
    spy.mockRestore();
  });

  it("parses message and calls onEvent", () => {
    const onEvent = vi.fn();
    renderHook(() => useWikiEvents("biz-1", onEvent));
    const es = instances[0];
    es.onopen?.(new Event("open"));
    es.onmessage?.({
      data: JSON.stringify({
        type: "wiki:page_updated",
        business_id: "biz-1",
        page_path: "/a",
        timestamp: "t",
      }),
    } as MessageEvent);
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "wiki:page_updated", page_path: "/a" }),
    );
  });

  it("closes EventSource on unmount", () => {
    const onEvent = vi.fn();
    const { unmount } = renderHook(() => useWikiEvents("biz-1", onEvent));
    const es = instances[0];
    unmount();
    expect(es.close).toHaveBeenCalled();
  });
});
