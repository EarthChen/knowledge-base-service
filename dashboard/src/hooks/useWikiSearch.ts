import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { WikiSearchResponse, WikiSemanticSearchResponse } from "./wikiTypes";

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

export type WikiSemanticSearchBody = {
  query: string;
  repository: string;
  limit?: number;
};

export function useWikiSemanticSearch() {
  return useMutation<WikiSemanticSearchResponse, ApiError, WikiSemanticSearchBody>({
    mutationFn: ({ query, repository, limit = 20 }) =>
      api<WikiSemanticSearchResponse>("/wiki/semantic-search", {
        method: "POST",
        body: JSON.stringify({ query, repository, limit }),
      }),
  });
}
