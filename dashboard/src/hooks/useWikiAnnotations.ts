import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { WikiAnnotation } from "./wikiTypes";

export function useWikiAnnotations(businessId: string, pageUid: string) {
  const queryClient = useQueryClient();
  const queryKey = queryKeys.wiki.annotations(businessId, pageUid);

  const query = useQuery<WikiAnnotation[]>({
    queryKey,
    queryFn: async () => {
      const raw = await api<unknown>(`/wiki/pages/${encodeURIComponent(pageUid)}/annotations`);
      return Array.isArray(raw) ? (raw as WikiAnnotation[]) : [];
    },
    enabled: !!businessId.trim() && !!pageUid,
  });

  const create = useMutation<WikiAnnotation, ApiError, {
    text_range_start: number;
    text_range_end: number;
    selected_text?: string;
    comment: string;
    author: string;
  }>({
    mutationFn: (body) =>
      api<WikiAnnotation>(`/wiki/pages/${encodeURIComponent(pageUid)}/annotations`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const remove = useMutation<void, ApiError, string>({
    mutationFn: (annotationId: string) =>
      api<void>(`/wiki/annotations/${encodeURIComponent(annotationId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  return { ...query, create, remove };
}
