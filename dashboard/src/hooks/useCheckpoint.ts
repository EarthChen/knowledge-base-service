import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export interface CheckpointInfo {
  business_id: string;
  db_path: string;
  last_modified: number;
  size_bytes: number;
}

export function useCheckpoint(businessId: string) {
  return useQuery({
    queryKey: ["checkpoint", businessId],
    queryFn: async (): Promise<CheckpointInfo | null> => {
      const data = await api<{ checkpoint?: CheckpointInfo | null }>(
        `/wiki/${encodeURIComponent(businessId)}/checkpoint`,
      );
      return data.checkpoint ?? null;
    },
    enabled: !!businessId,
  });
}

export function useDeleteCheckpoint(businessId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api(`/wiki/${encodeURIComponent(businessId)}/checkpoint`, {
        method: "DELETE",
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["checkpoint", businessId] });
    },
  });
}
