import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiGlobalSearchResponse } from "./wikiTypes";

export type WikiGlobalSearchBody = {
  query: string;
  mode?: "hybrid" | "graph" | "semantic" | "keyword";
  limit?: number;
  min_score?: number;
  repositories?: string[] | null;
};

export function useWikiGlobalSearch() {
  return useMutation<WikiGlobalSearchResponse, Error, WikiGlobalSearchBody>({
    mutationFn: (body) =>
      api<WikiGlobalSearchResponse>("/wiki/search/global", {
        method: "POST",
        body: JSON.stringify({
          mode: "hybrid",
          limit: 36,
          min_score: 0,
          repositories: null,
          ...body,
        }),
      }),
  });
}
