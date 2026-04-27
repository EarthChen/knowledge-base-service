import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface PatchPayload {
  pageUid: string;
  content: string;
  editReason?: string;
  expectedVersion?: number;
}

export interface PatchWikiPageResult {
  ok: boolean;
  version?: number;
  version_mismatch_warning?: string;
  [key: string]: unknown;
}

export function usePatchWikiPage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      pageUid,
      content,
      editReason,
      expectedVersion,
    }: PatchPayload): Promise<PatchWikiPageResult> => {
      return api<PatchWikiPageResult>(
        `/wiki/pages/${encodeURIComponent(pageUid)}/content`,
        {
          method: "PATCH",
          body: JSON.stringify({
            content,
            edit_reason: editReason ?? "",
            expected_version: expectedVersion ?? null,
          }),
        },
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}
