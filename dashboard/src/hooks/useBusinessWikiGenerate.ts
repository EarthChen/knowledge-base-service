import { useMutation } from "@tanstack/react-query";
import type { TaskInfo } from "../api/types";
import { ApiError, businessWikiGenerate } from "../api/client";

export function useBusinessWikiGenerate() {
  return useMutation<TaskInfo, ApiError, { businessId: string; language: string }>({
    mutationFn: (vars: { businessId: string; language: string }) =>
      businessWikiGenerate(vars.businessId, vars.language),
  });
}
