import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiTreeResponse } from "./wikiTypes";

export function useWikiTree(
  businessId: string,
  viewType: string,
  wikiTier: string | null = null,
) {
  const tierParam =
    wikiTier === "standard" || wikiTier === "essential" || wikiTier === "comprehensive"
      ? `&wiki_tier=${encodeURIComponent(wikiTier)}`
      : "";
  return useQuery<WikiTreeResponse>({
    queryKey: queryKeys.wiki.tree(businessId, viewType, wikiTier ?? "all"),
    queryFn: () =>
      api<WikiTreeResponse>(
        `/wiki/tree?business_id=${encodeURIComponent(businessId)}&view=${encodeURIComponent(viewType)}${tierParam}`,
      ),
    enabled: !!businessId,
  });
}
