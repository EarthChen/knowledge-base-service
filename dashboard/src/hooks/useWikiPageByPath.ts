import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiPageDetail } from "./wikiTypes";

export function useWikiPageByPath(
  businessId: string,
  path: string | undefined,
  options?: { enabled?: boolean },
) {
  const trimmed = path?.trim() ?? "";
  const pathEnabled = Boolean(businessId.trim() && trimmed.length > 0);
  const userEnabled = options?.enabled ?? true;
  return useQuery<WikiPageDetail>({
    queryKey: ["wiki", "page-by-path", businessId, trimmed],
    queryFn: () =>
      api<WikiPageDetail>(
        `/wiki/pages/by-path?business_id=${encodeURIComponent(businessId)}&path=${encodeURIComponent(trimmed)}`,
      ),
    enabled: pathEnabled && userEnabled,
    staleTime: 30_000,
  });
}
