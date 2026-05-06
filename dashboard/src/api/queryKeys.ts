/** TanStack Query key factory — keeps keys consistent for lookups and invalidation. */

export interface ArchitectureSearchQueryOptions {
  repository?: string;
  search?: string;
  offset?: number;
  limit?: number;
}

export const queryKeys = {
  health: ["health"] as const,
  stats: (repo?: string) => ["stats", repo] as const,
  /** Prefix for invalidating every `stats` query. */
  statsAll: ["stats"] as const,
  p2Stats: ["p2-stats"] as const,
  healthStats: ["stats", "health"] as const,
  repositories: ["repositories"] as const,
  hybridQuick: (trimmed: string) => ["hybrid-quick", trimmed] as const,
  webhookConfig: ["webhook-config"] as const,
  indexTasks: ["index-tasks"] as const,
  indexTask: (taskId: string | null) => ["index-task", taskId] as const,
  codeSnippet: (uid: string | null) => ["code-snippet", uid] as const,
  documents: (repository?: string) => ["documents", repository] as const,
  document: (uid: string | null) => ["document", uid] as const,
  syncSchedules: ["sync-schedules"] as const,
  architectureSearch: (layer: string, options: ArchitectureSearchQueryOptions) =>
    ["architecture-search", layer, options] as const,
  fileTree: (repository: string) => ["file-tree", repository] as const,
  fileContent: (repository: string, filePath: string) =>
    ["file-content", repository, filePath] as const,
  fileEntities: (filePath: string) => ["file-entities", filePath] as const,

  settings: ["settings"] as const,
  settingsCategory: (category: string) => ["settings", category] as const,
  businessRepositories: (businessId: string) => ["business", businessId, "repositories"] as const,

  wiki: {
    /** Prefix invalidation for wiki domain. */
    all: ["wiki"] as const,
    pages: (businessId: string) => ["wiki", "pages", businessId] as const,
    page: (businessId: string, path: string) => ["wiki", "page", businessId, path] as const,
    pathForSourceEntity: (businessId: string, uid: string) =>
      ["wiki", "pathForSourceEntity", businessId, uid] as const,
    diff: (businessId: string, pageUid: string, fromVersion: number, toVersion: number) =>
      ["wiki", "diff", businessId, pageUid, fromVersion, toVersion] as const,
    annotations: (businessId: string, pageUid: string) =>
      ["wiki", "annotations", businessId, pageUid] as const,
    quality: (businessId: string) => ["wiki", "quality", businessId] as const,
    documentationQualitySummary: (repo: string) =>
      ["wiki", "quality", "documentation-summary", repo] as const,
    navigation: (repository: string, pagePath: string) =>
      ["wiki", "navigation", repository, pagePath] as const,
    references: (businessId: string, pageUid: string) =>
      ["wiki", "references", businessId, pageUid] as const,
    referencesGraph: (businessId: string) => ["wiki", "references", businessId, "graph"] as const,
    coverage: (businessId: string) => ["wiki", "coverage", businessId] as const,
    tree: (businessId: string, viewType: string, wikiTier: string) =>
      ["wiki", "tree", businessId, viewType, wikiTier] as const,
    topicTree: (businessId: string) => ["wiki", "topic-tree", businessId] as const,
    domainTree: (businessId: string) => ["wiki", "domain-tree", businessId] as const,
    domainEdges: (businessId: string) => ["wiki", "domain-edges", businessId] as const,
    versions: (businessId: string, pageUid: string) =>
      ["wiki", "versions", businessId, pageUid] as const,
    businessFlows: (businessId: string) => ["wiki", "business-flows", businessId] as const,
    pageByPath: (businessId: string, path: string, repository?: string) =>
      ["wiki", "page-by-path", businessId, path, repository ?? ""] as const,
    entities: (businessId: string, pagePath: string, repository: string) =>
      ["wiki", "entities", businessId, pagePath, repository] as const,
  },
} as const;
