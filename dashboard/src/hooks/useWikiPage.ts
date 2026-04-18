import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WikiPageDetail } from "./wikiTypes";

export function wikiPageQueryKey(repository: string, path: string) {
  return ["wiki", "page", repository, path] as const;
}

function encodeWikiPath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

export function useWikiPage(repository: string | undefined, path: string | undefined) {
  const trimmed = path?.trim() ?? "";
  return useQuery({
    queryKey: wikiPageQueryKey(repository ?? "", trimmed),
    queryFn: () =>
      api<WikiPageDetail>(
        `/wiki/${encodeURIComponent(repository!)}/pages/${encodeWikiPath(trimmed)}`,
        { method: "GET" },
      ),
    enabled: Boolean(repository?.trim() && trimmed.length > 0),
  });
}
