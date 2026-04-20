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
