import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidates all wiki-related queries after a business wiki regeneration (or similar broad invalidation).
 *
 * Query keys vary: some put `businessId` at index 2, others use `pageUid`, repository, or fixed segments.
 * Matching only `k[2] === businessId` misses `claim-history`, `quality`, `navigation`, etc., so we invalidate
 * every query whose key starts with `"wiki"`.
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
      return k[0] === "wiki";
    },
  });
}
