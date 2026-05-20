import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiPageEntitiesApiResponse } from "./wikiTypes";

export function encodeWikiPagePathForUrl(pagePath: string): string {
  return pagePath
    .split("/")
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

export async function fetchWikiPageEntities(
  businessId: string,
  pagePath: string,
  repository?: string,
): Promise<WikiPageEntitiesApiResponse> {
  const pathPart = encodeWikiPagePathForUrl(pagePath);
  const qs = new URLSearchParams({ business_id: businessId.trim() });
  const repo = repository?.trim();
  if (repo) qs.set("repository", repo);
  return api<WikiPageEntitiesApiResponse>(`/wiki/pages/${pathPart}/entities?${qs}`);
}

export function useWikiEntities(
  pagePath: string | null | undefined,
  businessId: string | null | undefined,
  repository?: string,
) {
  const trimmedPath = pagePath?.trim() ?? "";
  const trimmedBiz = businessId?.trim() ?? "";
  const repoKey = repository?.trim() ?? "";

  return useQuery({
    queryKey: queryKeys.wiki.entities(trimmedBiz, trimmedPath, repoKey),
    queryFn: async () => {
      if (!trimmedPath || !trimmedBiz) {
        return { page_path: "", entities: [] };
      }
      try {
        return await fetchWikiPageEntities(trimmedBiz, trimmedPath, repository);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          return { page_path: trimmedPath, entities: [] };
        }
        throw e;
      }
    },
    enabled: Boolean(trimmedPath && trimmedBiz),
  });
}
