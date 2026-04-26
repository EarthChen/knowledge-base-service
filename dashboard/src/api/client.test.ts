import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { ApiError, api, setToken, API_BASE } from "./client";

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
});
