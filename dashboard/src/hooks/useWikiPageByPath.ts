import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiPageDetail } from "./wikiTypes";

/**
 * Load page via business WikiSpace tree; on 404 fall back to repository-scoped lookup
 * (module pages may exist on ``WikiPage`` without ``WikiSpace`` HAS_CHILD linkage).
 *
 * When ``repository`` is supplied (e.g. from global search), the backend tries a
 * direct repo-scoped lookup before falling back to the business space tree.
 */
export async function fetchWikiPageByPath(
  businessId: string,
  path: string,
  repository?: string,
): Promise<WikiPageDetail> {
  const qs = new URLSearchParams({
    business_id: businessId,
    path,
  });
  if (repository) qs.set("repository", repository);

  return api<WikiPageDetail>(`/wiki/pages/by-path?${qs.toString()}`);
}

export function useWikiPageByPath(
  businessId: string,
  path: string | undefined,
  options?: { enabled?: boolean; repository?: string },
) {
  const trimmed = path?.trim() ?? "";
  const pathEnabled = Boolean(businessId.trim() && trimmed.length > 0);
  const userEnabled = options?.enabled ?? true;
  const repository = options?.repository;
  return useQuery<WikiPageDetail>({
    queryKey: queryKeys.wiki.pageByPath(businessId, trimmed, repository),
    queryFn: () => fetchWikiPageByPath(businessId, trimmed, repository),
    enabled: pathEnabled && userEnabled,
  });
}
