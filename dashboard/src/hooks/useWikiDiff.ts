import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiDiff } from "./wikiTypes";

export function useWikiDiff(pageUid: string, fromVersion: number, toVersion: number) {
  return useQuery<WikiDiff>({
    queryKey: ["wiki", "diff", pageUid, fromVersion, toVersion],
    queryFn: () =>
      api<WikiDiff>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/diff?from=${fromVersion}&to=${toVersion}`,
      ),
    enabled: !!pageUid && fromVersion > 0 && toVersion > 0 && fromVersion !== toVersion,
  });
}
