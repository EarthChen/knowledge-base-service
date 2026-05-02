import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { WikiSearchResponse } from "./wikiTypes";

export type WikiSearchBody = {
  repository: string;
  query: string;
  mode?: "hybrid" | "graph" | "semantic" | "keyword";
  limit?: number;
  min_score?: number;
  scope?: string | null;
};

export function useWikiSearch() {
  return useMutation<WikiSearchResponse, ApiError, WikiSearchBody>({
    mutationFn: (body) =>
      api<WikiSearchResponse>("/wiki/search", {
        method: "POST",
        body: JSON.stringify({
          mode: "hybrid",
          limit: 12,
          min_score: 0,
          scope: null,
          ...body,
        }),
      }),
  });
}
