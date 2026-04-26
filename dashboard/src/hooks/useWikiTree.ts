import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiTreeResponse } from "./wikiTypes";

export function useWikiTree(businessId: string, viewType: string) {
  return useQuery<WikiTreeResponse>({
    queryKey: ["wiki", "tree", businessId, viewType],
    queryFn: () =>
      api<WikiTreeResponse>(
        `/wiki/tree?business_id=${encodeURIComponent(businessId)}&view=${encodeURIComponent(viewType)}`,
      ),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}
