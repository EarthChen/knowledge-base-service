import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export interface NavigationContext {
  parent_path: string | null;
  parent_title: string | null;
  sibling_paths: string[];
  child_paths: string[];
  related_flow_paths: string[];
  breadcrumbs: Array<[string, string]>;
}

export function useWikiNavigation(repository: string, pagePath: string) {
  const trimmedRepo = repository.trim();
  const trimmedPath = pagePath.trim();
  return useQuery<NavigationContext>({
    queryKey: ["wiki", "navigation", trimmedRepo, trimmedPath],
    queryFn: () =>
      api<NavigationContext>(
        `/wiki/${encodeURIComponent(trimmedRepo)}/navigation?path=${encodeURIComponent(trimmedPath)}`,
      ),
    enabled: Boolean(trimmedRepo && trimmedPath),
    staleTime: 300_000,
  });
}
