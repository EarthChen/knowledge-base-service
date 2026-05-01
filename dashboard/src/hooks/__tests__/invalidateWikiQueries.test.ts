import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { invalidateWikiQueriesForBusiness } from "../invalidateWikiQueries";

describe("invalidateWikiQueriesForBusiness", () => {
  let queryClient: QueryClient;
  let invalidateSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  });

  afterEach(() => {
    invalidateSpy.mockRestore();
  });

  it("does not call invalidateQueries when businessId is empty or whitespace-only", async () => {
    await invalidateWikiQueriesForBusiness(queryClient, "");
    await invalidateWikiQueriesForBusiness(queryClient, "   ");
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("uses a predicate that only matches wiki keys containing the trimmed business id", async () => {
    await invalidateWikiQueriesForBusiness(queryClient, "  biz-a  ");
    expect(invalidateSpy).toHaveBeenCalledTimes(1);
    const predicate = invalidateSpy.mock.calls[0][0].predicate!;
    expect(
      predicate({ queryKey: ["wiki", "home", "biz-a", "slug"] } as never),
    ).toBe(true);
    expect(
      predicate({ queryKey: ["wiki", "biz-a"] } as never),
    ).toBe(true);
    expect(
      predicate({ queryKey: ["wiki", "home", "biz-b"] } as never),
    ).toBe(false);
    expect(
      predicate({ queryKey: ["docs", "wiki", "biz-a"] } as never),
    ).toBe(false);
    expect(
      predicate({ queryKey: ["wiki", "navigation", "repo", "/x"] } as never),
    ).toBe(false);
  });
});
