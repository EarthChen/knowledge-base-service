import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";

export type WikiPathForSourceEntityResponse = {
  path: string | null;
};

export function useWikiPathForSourceEntity(
  businessId: string,
  entityUid: string | null | undefined,
  options?: { enabled?: boolean },
) {
  const uid = (entityUid ?? "").trim();
  const enabled = (options?.enabled ?? true) && Boolean(businessId.trim() && uid);
  return useQuery<WikiPathForSourceEntityResponse>({
    queryKey: queryKeys.wiki.pathForSourceEntity(businessId, uid),
    queryFn: () =>
      api<WikiPathForSourceEntityResponse>(
        `/wiki/pages/by-source-entity?business_id=${encodeURIComponent(
          businessId,
        )}&entity_uid=${encodeURIComponent(uid)}`,
      ),
    enabled,
    staleTime: 60_000,
  });
}
