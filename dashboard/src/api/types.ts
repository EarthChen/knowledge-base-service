export interface Business {
  id: string;
  name: string;
  description: string;
  created_at: number;
}

export interface BusinessesResponse {
  businesses: Business[];
  total: number;
}

export interface GraphStats {
  function_count: number;
  class_count: number;
  module_count: number;
  document_count: number;
  calls_count: number;
  inherits_count: number;
  imports_count: number;
  contains_count: number;
  references_count: number;
  total_nodes: number;
  total_edges: number;
}

export interface Repository {
  repository: string;
  nodes: number;
}

export interface RepositoriesResponse {
  repositories: Repository[];
  total: number;
}

export interface SearchMatch {
  type: string;
  name: string;
  file: string;
  line: number | null;
  score: number;
  signature?: string;
  docstring?: string;
  content?: string;
  fqn?: string;
  uid?: string;
}

export interface CodeSnippetResponse {
  name: string;
  file: string;
  start_line: number;
  end_line: number;
  code_snippet: string;
  signature: string;
  docstring: string;
  fqn: string;
  type: string;
}

export interface SearchResponse {
  matches: SearchMatch[];
  total: number;
  query: string;
}

export interface HybridSearchResponse {
  semantic_matches: SearchMatch[];
  graph_context: unknown[];
  total: number;
  query: string;
}

export interface IndexResponse {
  stats?: Record<string, number>;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: string;
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  file: string;
  line: number;
  is_center?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphExploreResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface DocumentSection {
  title: string;
  content: string;
  start_line: number;
  uid: string;
}

export interface DocumentItem {
  file: string;
  title: string;
  repository: string;
  uid: string;
  sections: { title: string; uid: string; start_line: number }[];
}

export interface DocumentsResponse {
  documents: DocumentItem[];
  total: number;
}

export interface DocumentDetail {
  title: string;
  file: string;
  repository: string;
  sections: DocumentSection[];
}
