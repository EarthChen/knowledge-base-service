import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { encodeWikiPath } from "../utils/wikiPath";
import type { WikiPageDetail } from "./wikiTypes";

export function wikiPageQueryKey(businessId: string, path: string) {
  return queryKeys.wiki.page(businessId, path);
}

export function useWikiPage(businessId: string | undefined, path: string | undefined) {
  const trimmed = path?.trim() ?? "";
  return useQuery({
    queryKey: wikiPageQueryKey(businessId ?? "", trimmed),
    queryFn: () =>
      api<WikiPageDetail>(
        `/wiki/${encodeURIComponent(businessId!)}/pages/${encodeWikiPath(trimmed)}`,
        { method: "GET" },
      ),
    enabled: Boolean(businessId?.trim() && trimmed.length > 0),
  });
}
