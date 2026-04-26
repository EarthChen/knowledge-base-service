import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiReferencesResponse } from "./wikiTypes";

export function useWikiReferences(pageUid: string) {
  return useQuery<WikiReferencesResponse>({
    queryKey: ["wiki", "references", pageUid],
    queryFn: () =>
      api<WikiReferencesResponse>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/references`,
      ),
    enabled: !!pageUid,
    staleTime: 30_000,
  });
}
