import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiVersion } from "./wikiTypes";

export function useWikiVersions(pageUid: string) {
  return useQuery<WikiVersion[]>({
    queryKey: ["wiki", "versions", pageUid],
    queryFn: () => api<WikiVersion[]>(`/wiki/pages/${encodeURIComponent(pageUid)}/versions`),
    enabled: !!pageUid,
  });
}
