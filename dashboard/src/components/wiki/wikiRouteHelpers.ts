export function wikiHref(path?: string, params?: Record<string, string>): string {
  const sp = new URLSearchParams();
  if (path) sp.set("path", path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v) sp.set(k, v);
    }
  }
  const qs = sp.toString();
  return qs ? `/wiki?${qs}` : "/wiki";
}

export function wikiSearchHref(query: string): string {
  return `/search?mode=wiki&q=${encodeURIComponent(query)}`;
}

const VIEW_TYPES = new Set(["business_domain", "code_structure"]);
const TOOL_TABS = new Set([
  "page",
  "coverage",
  "export",
  "health",
  "insights",
  "refgraph",
  "research",
  "flows",
  "knowledge_graph",
]);

const WIKI_TIERS = new Set(["standard", "essential", "comprehensive"] as const);

export function parseWikiSearchParams(search: URLSearchParams) {
  const rawView = search.get("view");
  const viewType: "business_domain" | "code_structure" =
    rawView && VIEW_TYPES.has(rawView)
      ? (rawView as "business_domain" | "code_structure")
      : "business_domain";
  const rawTool = search.get("tool");
  const rawWikiTier = search.get("wiki_tier");
  const wikiTier: "standard" | "essential" | "comprehensive" | null =
    rawWikiTier && WIKI_TIERS.has(rawWikiTier as "standard" | "essential" | "comprehensive")
      ? (rawWikiTier as "standard" | "essential" | "comprehensive")
      : null;
  const toolTab:
    | "page"
    | "coverage"
    | "export"
    | "health"
    | "insights"
    | "refgraph"
    | "research"
    | "flows"
    | "knowledge_graph" =
    rawTool && TOOL_TABS.has(rawTool)
      ? (rawTool as
          | "page"
          | "coverage"
          | "export"
          | "health"
          | "insights"
          | "refgraph"
          | "research"
          | "flows"
          | "knowledge_graph")
      : "page";
  return {
    path: search.get("path") || null,
    viewType,
    businessId: search.get("business_id") || null,
    repo: search.get("repo") || null,
    toolTab,
    wikiTier,
  };
}
