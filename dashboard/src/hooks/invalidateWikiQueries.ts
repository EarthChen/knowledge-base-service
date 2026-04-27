import type { QueryClient } from "@tanstack/react-query";

/** All wiki query keys use `["wiki", <segment>, businessId, ...]` — invalidate everything for this business. */
export function invalidateWikiQueriesForBusiness(
  queryClient: QueryClient,
  businessId: string,
) {
  const b = businessId.trim();
  if (!b) return Promise.resolve();
  return queryClient.invalidateQueries({
    predicate: (q) => {
      const k = q.queryKey as unknown[];
      return k[0] === "wiki" && k[2] === b;
    },
  });
}
