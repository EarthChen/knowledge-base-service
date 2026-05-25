import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { setToken } from "../../api/client";
import { useWikiEvents } from "../useWikiEvents";

describe("useWikiEvents", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    setToken("");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps connectionStatus disconnected when businessId is blank", () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() => useWikiEvents("   ", onEvent));
    expect(result.current.connectionStatus).toBe("disconnected");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does not include token in the URL (uses Authorization header instead)", async () => {
    setToken("secret-tok");
    fetchSpy.mockImplementation(() => new Promise(() => {}));

    renderHook(() => useWikiEvents("biz-1", vi.fn()));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());

    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toContain("business_id=biz-1");
    expect(url).not.toContain("token=");
    expect(url).not.toContain("secret-tok");
    expect(opts.headers.Authorization).toBe("Bearer secret-tok");
  });

  it("sends auth via header not query param regardless of token value", async () => {
    fetchSpy.mockImplementation(() => new Promise(() => {}));

    renderHook(() => useWikiEvents("biz-1", vi.fn()));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());

    const [url] = fetchSpy.mock.calls[0];
    expect(url).not.toContain("token=");
  });

  it("sets connectionStatus to disconnected when disabled", () => {
    fetchSpy.mockImplementation(() => new Promise(() => {}));
    const onEvent = vi.fn();
    const { result } = renderHook(() => useWikiEvents("biz-1", onEvent, false));
    expect(result.current.connectionStatus).toBe("disconnected");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("aborts fetch on unmount", async () => {
    fetchSpy.mockImplementation(() => new Promise(() => {}));

    const onEvent = vi.fn();
    const { unmount } = renderHook(() => useWikiEvents("biz-1", onEvent));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());

    unmount();
    const signal = fetchSpy.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(true);
  });

  it("sets connectionStatus to reconnecting when fetch rejects", async () => {
    fetchSpy.mockRejectedValue(new Error("network"));

    const onEvent = vi.fn();
    const { result } = renderHook(() => useWikiEvents("biz-1", onEvent));

    await waitFor(() => expect(result.current.connectionStatus).toBe("reconnecting"), { timeout: 3000 });
  });
});
