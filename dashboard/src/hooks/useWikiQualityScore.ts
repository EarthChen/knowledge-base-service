import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiDocumentationQualitySummary, WikiQualityScoreResponse } from "./wikiTypes";

export function useWikiQualityScore(businessId: string) {
  return useQuery<WikiQualityScoreResponse>({
    queryKey: queryKeys.wiki.quality(businessId),
    queryFn: () =>
      api<WikiQualityScoreResponse>(`/wiki/quality-score?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 60_000,
  });
}

/** GET /wiki/{repository}/documentation-quality/summary — persisted page-level quality aggregates. */
export function useWikiDocumentationQualitySummary(repository: string, queryEnabled = true) {
  const repo = repository.trim();
  return useQuery<WikiDocumentationQualitySummary>({
    queryKey: queryKeys.wiki.documentationQualitySummary(repo),
    queryFn: () =>
      api<WikiDocumentationQualitySummary>(
        `/wiki/${encodeURIComponent(repo)}/documentation-quality/summary`,
      ),
    enabled: !!repo && queryEnabled,
    staleTime: 120_000,
  });
}
