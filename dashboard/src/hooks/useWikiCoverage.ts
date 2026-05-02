import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiCoverageResponse } from "./wikiTypes";

export function useWikiCoverage(businessId: string) {
  return useQuery<WikiCoverageResponse>({
    queryKey: queryKeys.wiki.coverage(businessId),
    queryFn: () =>
      api<WikiCoverageResponse>(
        `/wiki/coverage-report?business_id=${encodeURIComponent(businessId)}`,
      ),
    enabled: !!businessId,
    staleTime: 60_000,
  });
}
