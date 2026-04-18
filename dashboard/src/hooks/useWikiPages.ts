import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiPagesResponse } from "./wikiTypes";

export function wikiPagesQueryKey(repository: string) {
  return ["wiki", "pages", repository] as const;
}

export function useWikiPages(repository: string | undefined) {
  return useQuery({
    queryKey: wikiPagesQueryKey(repository ?? ""),
    queryFn: () =>
      api<WikiPagesResponse>(
        `/wiki/${encodeURIComponent(repository!)}/pages`,
        { method: "GET" },
      ),
    enabled: Boolean(repository?.trim()),
  });
}
