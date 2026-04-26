/** Shared wiki API types (frontend). */

export type WikiPageSummary = {
  path: string;
  title: string;
  scope: string;
};

export type WikiPagesResponse = {
  pages: WikiPageSummary[];
  total: number;
};

export type WikiSourceLocation = {
  file_path: string;
  start_line: number;
  end_line: number;
  fqn: string;
  repository: string;
};

export type WikiPageDetail = {
  path: string;
  title: string;
  content: string;
  diagrams: unknown[];
  source_locations: WikiSourceLocation[];
  method_locations: unknown[];
  context: Record<string, string>;
  /** ISO timestamp from page metadata when the server provides it. */
  generated_at?: string | null;
};

export type WikiSearchResult = {
  page_path: string;
  title: string;
  score: number;
  snippet: string;
  source_locations: Record<string, unknown>[];
  context: Record<string, string>;
};

export type WikiSearchResponse = {
  results: WikiSearchResult[];
  query_expansion: Record<string, unknown>;
  total: number;
};

export type WikiGlobalSearchResponse = {
  /** Top hits after global merge, each with ``context.repository`` set. */
  results: WikiSearchResult[];
  /** Same hits grouped by repository (insertion order follows global rank). */
  by_repository: Record<string, WikiSearchResult[]>;
  query_expansion: Record<string, unknown>;
  total: number;
  repositories_searched: string[];
  partial_errors: { repository: string; detail: string }[];
};

export type WikiAskSource = {
  entity: string;
  file_path: string;
  start_line: number;
  wiki_page: string;
  relevance_score: number;
};

export type WikiTreeNode = {
  uid: string;
  title: string;
  label: string;
  depth: number;
  sort_order: number;
  path: string;
  page_type: string;
  children?: WikiTreeNode[];
};

export type WikiTreeResponse = {
  tree: WikiTreeNode[];
  business_id: string;
  view_type: string;
};

/** Row from GET /wiki/pages/{uid}/references (outgoing uses target_uid; incoming uses source_uid). */
export type WikiReference = {
  relation_type: string;
  context: string;
  repository: string;
  title: string;
  path: string;
  target_uid?: string;
  source_uid?: string;
};

export type WikiReferencesResponse = {
  page_uid: string;
  outgoing: WikiReference[];
  incoming: WikiReference[];
};

export type WikiStalePage = {
  page_path: string;
  page_title: string;
  entity_commit: string;
  page_generated_at: string;
};

export type WikiKnowledgeGap = {
  entity: string;
  in_degree: number;
  wiki_tier: string | null;
};

export type WikiCoverageResponse = {
  total_entities: number;
  covered_entities: number;
  coverage_percentage: number;
  core_coverage: number;
  standard_coverage: number;
  stale_pages: WikiStalePage[];
  stale_page_count: number;
  knowledge_gaps: WikiKnowledgeGap[];
  knowledge_gap_count: number;
};

export type BusinessWikiExportBody = {
  business_id: string;
  format: "markdown" | "zip" | "git" | "obsidian" | "mkdocs";
  view_type: "business_domain" | "code_structure" | "both";
  min_tier: "core" | "standard" | "skeleton";
  git_config?: {
    remote_url: string;
    branch: string;
    commit_message_prefix: string;
  };
};

export type BusinessWikiExportResponse = {
  status: string;
  format: string;
  file_count: number;
  output_path?: string;
  download_url?: string;
};

export type WikiAnnotation = {
  annotation_id: string;
  page_uid: string;
  text_range_start: number;
  text_range_end: number;
  /** Plain text that was selected when the annotation was created; used for robust re-highlighting. */
  selected_text?: string | null;
  comment: string;
  author: string;
  created_at: string;
};

export type WikiVersion = {
  version: number;
  content_hash: string;
  generated_at: string;
  change_summary: string;
};

export type WikiDiff = {
  from_version: number;
  to_version: number;
  hunks: Array<{
    old_start: number;
    old_lines: number;
    new_start: number;
    new_lines: number;
    content: string;
  }>;
};

export type WikiEventType =
  | "wiki:page_updated"
  | "wiki:generation_started"
  | "wiki:generation_completed"
  | "wiki:generation_failed";

export type WikiEvent = {
  type: WikiEventType;
  business_id: string;
  page_path?: string;
  timestamp: string;
  payload?: Record<string, unknown>;
};
