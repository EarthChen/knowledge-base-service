import { useMutation } from "@tanstack/react-query";
import { ApiError, businessWikiExport } from "../api/client";
import type { BusinessWikiExportBody, BusinessWikiExportResponse } from "./wikiTypes";

export function useBusinessWikiExport() {
  return useMutation<BusinessWikiExportResponse, ApiError, BusinessWikiExportBody>({
    mutationFn: (body: BusinessWikiExportBody) => businessWikiExport(body),
  });
}
