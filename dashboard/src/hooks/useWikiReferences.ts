import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiReferencesResponse } from "./wikiTypes";

export function useWikiReferences(businessId: string, pageUid: string) {
  return useQuery<WikiReferencesResponse>({
    queryKey: queryKeys.wiki.references(businessId, pageUid),
    queryFn: () =>
      api<WikiReferencesResponse>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/references`,
      ),
    enabled: !!businessId.trim() && !!pageUid,
    staleTime: 30_000,
  });
}
