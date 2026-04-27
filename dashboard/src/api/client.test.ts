import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import {
  ApiError,
  api,
  authHeaders,
  getCurrentBusiness,
  businessWikiExport,
  businessWikiGenerate,
  getGraphInsights,
  getToken,
  setToken,
  API_BASE,
  triggerEnrich,
  wikiExportExecute,
  wikiExportPreview,
  wikiGenerate,
  wikiLint,
  wikiTaskStatus,
} from "./client";
import type { BusinessWikiExportBody } from "../hooks/wikiTypes";

const originalFetch = globalThis.fetch;

function mockResponse(body: string, init: { status: number; statusText?: string }) {
  return new Response(body, {
    status: init.status,
    statusText: init.statusText ?? "Error",
  });
}

describe("api client", () => {
  beforeEach(() => {
    setToken("");
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    localStorage.removeItem("kb_business_id");
  });

  it("throws ApiError with detail string from JSON error body", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        mockResponse(JSON.stringify({ detail: "forbidden" }), { status: 403 }),
      );
    try {
      await api(`${API_BASE}/x`);
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(403);
      expect(err.message).toBe("forbidden");
      return;
    }
    expect.fail("expected throw");
  });

  it("stringifies object detail in ApiError", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        mockResponse(JSON.stringify({ detail: { field: "bad" } }), { status: 422 }),
      );
    try {
      await api(`${API_BASE}/x`);
    } catch (e) {
      const err = e as ApiError;
      expect(err.status).toBe(422);
      expect(err.message).toContain("field");
      return;
    }
    expect.fail("expected throw");
  });

  it("uses error field when detail is absent", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        mockResponse(JSON.stringify({ error: "boom" }), { status: 500 }),
      );
    try {
      await api(`${API_BASE}/x`);
    } catch (e) {
      const err = e as ApiError;
      expect(err.message).toBe("boom");
      return;
    }
    expect.fail("expected throw");
  });

  it("parses non-JSON error body to raw wrapper", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      mockResponse("not-json", { status: 500 }),
    );
    try {
      await api(`${API_BASE}/x`);
    } catch (e) {
      const err = e as ApiError;
      expect(err.body).toEqual({ raw: "not-json" });
      return;
    }
    expect.fail("expected throw");
  });

  it("rejects cross-origin absolute URLs for api()", async () => {
    let threw = false;
    try {
      await api("https://example.com/mal", {});
    } catch (e) {
      threw = true;
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).message).toContain("Cross-origin");
    }
    expect(threw).toBe(true);
  });

  it("returns parsed JSON for ok responses and empty string body", async () => {
    globalThis.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (String(url).endsWith("/ok-json")) {
        return mockResponse(JSON.stringify({ a: 1 }), { status: 200, statusText: "OK" });
      }
      return new Response(null, { status: 200, statusText: "No Content" });
    });
    await expect(api(`${API_BASE}/ok-json`)).resolves.toEqual({ a: 1 });
    await expect(api(`${API_BASE}/empty`)).resolves.toBeNull();
  });

  it("treats non-JSON 200 body as { raw: text }", async () => {
    globalThis.fetch = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response("not-json {", { status: 200, statusText: "OK" })));
    await expect(api(`${API_BASE}/raw-ok`)).resolves.toEqual({ raw: "not-json {" });
  });

  it("allows same-origin http URL when it matches window.location", async () => {
    const origin = window.location.origin;
    globalThis.fetch = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, statusText: "OK" })));
    await expect(api(`${origin}${API_BASE}/by-full-url`)).resolves.toEqual({});
  });
});

describe("getCurrentBusiness re-export", () => {
  it("returns business id (default or stored)", () => {
    expect(getCurrentBusiness()).toBe("default");
  });
});

describe("getToken, setToken, authHeaders", () => {
  beforeEach(() => {
    setToken("");
  });

  it("round-trips the token in localStorage and includes it in auth headers", () => {
    expect(getToken()).toBe("");
    setToken("abc");
    expect(getToken()).toBe("abc");
    const h = authHeaders();
    expect(h.Authorization).toBe("Bearer abc");
  });

  it("setToken with empty value clears the token", () => {
    setToken("x");
    setToken("");
    expect(getToken()).toBe("");
    expect("Authorization" in authHeaders()).toBe(false);
  });
});

function mockOkJson(data: unknown) {
  return new Response(JSON.stringify(data), { status: 200, statusText: "OK" });
}

describe("API helper functions", () => {
  const task = { task_id: "1", status: "done", mode: "x" };
  const exportRes = { status: "ok", format: "md", file_count: 0 };

  beforeEach(() => {
    setToken("");
    globalThis.fetch = vi.fn().mockImplementation(() => Promise.resolve(mockOkJson(task)));
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("POST /enrich with X-Business-Id and body", async () => {
    await expect(triggerEnrich("biz", { repository: "r" })).resolves.toEqual(task);
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledWith(
      expect.stringContaining("/enrich"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Business-Id": "biz" } as Record<string, string>),
      }),
    );
  });

  it("POST wiki lint and generate", async () => {
    await expect(wikiLint("my/repo", "stale")).resolves.toEqual(task);
    await expect(
      wikiGenerate("my/repo", "all", "structure", "zh"),
    ).resolves.toEqual(task);
    const calls = vi.mocked(globalThis.fetch).mock.calls;
    const lintBody = (calls[0][1] as { body: string })?.body;
    expect(lintBody).toContain("stale");
  });

  it("GET graph insights, wiki task, and business generate", async () => {
    vi.mocked(globalThis.fetch).mockImplementation((url) => {
      if (String(url).includes("/graph/insights/")) {
        return Promise.resolve(mockOkJson({ report: 1 } as { report: number }));
      }
      return Promise.resolve(mockOkJson({ task_id: "t" }));
    });
    await expect(getGraphInsights("g/r")).resolves.toEqual({ report: 1 });
    await expect(wikiTaskStatus("a/b")).resolves.toEqual({ task_id: "t" });
    await expect(businessWikiGenerate("bid", "en")).resolves.toEqual({ task_id: "t" });
  });

  it("export preview, execute with files, and business export", async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => Promise.resolve(mockOkJson(exportRes)));
    await expect(wikiExportPreview("r1", "/tmp/t")).resolves.toEqual(exportRes);
    await expect(
      wikiExportExecute("r1", "/tmp", ["/a.md"]),
    ).resolves.toEqual(exportRes);
    const lastCall = vi.mocked(globalThis.fetch).mock.calls.at(-1);
    const lastBody = (lastCall?.[1] as { body: string } | undefined)?.body;
    expect(lastBody).toContain("selected_files");
    const body: BusinessWikiExportBody = {
      business_id: "b",
      format: "markdown",
      view_type: "both",
      min_tier: "core",
    };
    await expect(businessWikiExport(body)).resolves.toEqual(exportRes);
  });
});
