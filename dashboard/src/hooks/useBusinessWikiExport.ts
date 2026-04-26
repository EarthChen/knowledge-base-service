import { useMutation } from "@tanstack/react-query";
import { businessWikiExport } from "../api/client";
import type { BusinessWikiExportBody } from "./wikiTypes";

export function useBusinessWikiExport() {
  return useMutation({
    mutationFn: (body: BusinessWikiExportBody) => businessWikiExport(body),
  });
}
