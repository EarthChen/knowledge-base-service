import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiPageDetail } from "./wikiTypes";

export function useWikiPageByPath(businessId: string, path: string | undefined) {
  const trimmed = path?.trim() ?? "";
  return useQuery<WikiPageDetail>({
    queryKey: ["wiki", "page-by-path", businessId, trimmed],
    queryFn: () =>
      api<WikiPageDetail>(
        `/wiki/pages/by-path?business_id=${encodeURIComponent(businessId)}&path=${encodeURIComponent(trimmed)}`,
      ),
    enabled: Boolean(businessId.trim() && trimmed.length > 0),
    staleTime: 30_000,
  });
}
