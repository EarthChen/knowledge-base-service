import { useMutation } from "@tanstack/react-query";
import { businessWikiGenerate } from "../api/client";

export function useBusinessWikiGenerate() {
  return useMutation({
    mutationFn: (vars: { businessId: string; language: string }) =>
      businessWikiGenerate(vars.businessId, vars.language),
  });
}
