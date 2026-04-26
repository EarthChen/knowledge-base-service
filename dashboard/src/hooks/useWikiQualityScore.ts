import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiQualityScoreResponse } from "./wikiTypes";

export function useWikiQualityScore(businessId: string) {
  return useQuery<WikiQualityScoreResponse>({
    queryKey: ["wiki", "quality", businessId],
    queryFn: () =>
      api<WikiQualityScoreResponse>(`/wiki/quality-score?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 60_000,
  });
}
