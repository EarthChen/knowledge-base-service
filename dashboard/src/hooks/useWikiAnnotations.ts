import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiAnnotation } from "./wikiTypes";

export function useWikiAnnotations(pageUid: string) {
  const queryClient = useQueryClient();
  const queryKey = ["wiki", "annotations", pageUid];

  const query = useQuery<WikiAnnotation[]>({
    queryKey,
    queryFn: () => api<WikiAnnotation[]>(`/wiki/pages/${encodeURIComponent(pageUid)}/annotations`),
    enabled: !!pageUid,
  });

  const create = useMutation({
    mutationFn: (body: {
      text_range_start: number;
      text_range_end: number;
      comment: string;
      author: string;
    }) =>
      api<WikiAnnotation>(`/wiki/pages/${encodeURIComponent(pageUid)}/annotations`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const remove = useMutation({
    mutationFn: (annotationId: string) =>
      api<void>(`/wiki/annotations/${encodeURIComponent(annotationId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  return { ...query, create, remove };
}
