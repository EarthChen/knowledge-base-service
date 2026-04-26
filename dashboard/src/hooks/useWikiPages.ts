import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiPagesResponse } from "./wikiTypes";

export function wikiPagesQueryKey(businessId: string) {
  return ["wiki", "pages", businessId] as const;
}

export function useWikiPages(businessId: string | undefined) {
  return useQuery({
    queryKey: wikiPagesQueryKey(businessId ?? ""),
    queryFn: () =>
      api<WikiPagesResponse>(
        `/wiki/${encodeURIComponent(businessId!)}/pages`,
        { method: "GET" },
      ),
    enabled: Boolean(businessId?.trim()),
  });
}
