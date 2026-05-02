import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { encodeWikiPath } from "../utils/wikiPath";
import type { WikiPageDetail } from "./wikiTypes";

/**
 * Load page via business WikiSpace tree; on 404 fall back to repository-scoped lookup
 * (module pages may exist on ``WikiPage`` without ``WikiSpace`` HAS_CHILD linkage).
 */
export async function fetchWikiPageByPath(businessId: string, path: string): Promise<WikiPageDetail> {
  try {
    return await api<WikiPageDetail>(
      `/wiki/pages/by-path?business_id=${encodeURIComponent(businessId)}&path=${encodeURIComponent(path)}`,
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return await api<WikiPageDetail>(
        `/wiki/${encodeURIComponent(businessId)}/pages/${encodeWikiPath(path)}`,
      );
    }
    throw e;
  }
}

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
    queryFn: () => fetchWikiPageByPath(businessId, trimmed),
    enabled: pathEnabled && userEnabled,
    staleTime: 30_000,
  });
}
