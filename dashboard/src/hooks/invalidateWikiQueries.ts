import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates wiki-related queries scoped to `businessId` after regeneration (or similar).
 *
 * Most hooks use keys like `["wiki", ..., businessId, ...]`. Queries that omit `businessId` (e.g.
 * `["wiki","navigation", repo, path]`, `["wiki","quality","documentation-summary", repo]`,
 * `["wiki","claim-history", pageUid]`) are **not** matched by business id and stay cached until
 * their own TTL/refetch triggers.
 */
export function invalidateWikiQueriesForBusiness(
  queryClient: QueryClient,
  businessId: string,
) {
  const b = businessId.trim();
  if (!b) return Promise.resolve();
  return queryClient.invalidateQueries({
    predicate: (q) => {
      const k = q.queryKey as unknown[];
      return k[0] === "wiki" && k.includes(b);
    },
  });
}
