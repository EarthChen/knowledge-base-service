import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiVersion } from "./wikiTypes";

export function useWikiVersions(businessId: string, pageUid: string) {
  return useQuery<WikiVersion[]>({
    queryKey: ["wiki", "versions", businessId, pageUid],
    queryFn: () => api<WikiVersion[]>(`/wiki/pages/${encodeURIComponent(pageUid)}/versions`),
    enabled: !!businessId.trim() && !!pageUid,
  });
}
