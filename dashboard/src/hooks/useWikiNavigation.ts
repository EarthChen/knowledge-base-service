import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";

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
  const looksLikeRepo = trimmedRepo.includes("/");
  return useQuery<NavigationContext>({
    queryKey: queryKeys.wiki.navigation(trimmedRepo, trimmedPath),
    queryFn: () =>
      api<NavigationContext>(
        `/wiki/navigation/by-path?repository=${encodeURIComponent(trimmedRepo)}&path=${encodeURIComponent(trimmedPath)}`,
      ),
    enabled: Boolean(trimmedRepo && trimmedPath && looksLikeRepo),
    staleTime: 300_000,
  });
}
