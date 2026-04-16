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

export interface P2Stats {
  architecture_layers: Record<string, number>;
  event_tracking: {
    kafka_topics: number;
    producers: number;
    consumers: number;
  };
  rpc_contracts: {
    total_contracts: number;
    contract_methods: number;
  };
  cross_repo: {
    cross_repo_call_edges: number;
    di_dependency_edges: number;
    entity_table_edges: number;
  };
  quality_overview: null | Record<string, unknown>;
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
  task_id: string;
  status: string;
  mode: string;
  directory: string;
  stats?: Record<string, number>;
  [key: string]: unknown;
}

/** POST /enrich 请求体 */
export interface EnrichRequest {
  repository: string;
  force?: boolean;
}

/** 触发索引/补全类任务后的通用任务信息（含 enrich） */
export interface TaskInfo {
  task_id: string;
  status: string;
  mode: string;
  repository?: string;
  force?: boolean;
  directory?: string;
}

export interface IndexTaskProgress {
  phase: string;
  total_files: number;
  processed_files: number;
  current_file: string;
  stats: Record<string, number>;
  /** 服务端 LLM 增强模式：gateway | direct | 空 */
  enrichment_backend?: string;
  /** 当前任务已写入 business_summary 的实体数（进度或最终结果） */
  enriched_count?: number;
}

export interface IndexTask {
  task_id: string;
  status: "pending" | "running" | "completed" | "failed";
  mode: string;
  directory: string;
  repository: string | null;
  business_id: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: IndexTaskProgress;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface IndexTasksResponse {
  tasks: IndexTask[];
  total: number;
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
  level?: number;
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

export interface BusinessFlowMatch {
  name: string;
  description: string;
  category?: string;
  confidence_score?: number;
  score: number;
  code_locations?: Array<{
    name: string;
    file: string;
    line?: number;
    type?: string;
  }>;
}

export interface BusinessConceptMatch {
  name: string;
  description: string;
  aliases?: string[];
  category?: string;
  score: number;
}

export interface BusinessSearchResponse {
  flows?: BusinessFlowMatch[];
  concepts?: BusinessConceptMatch[];
}

export interface SyncSchedule {
  repo_name: string;
  git_url: string;
  branch: string | null;
  interval_minutes: number;
  enabled: boolean;
  last_sync_at: string | null;
  last_sync_status: string;
  last_sync_detail: string;
  created_at: string;
}

export interface SyncSchedulesResponse {
  schedules: SyncSchedule[];
  total: number;
}

export interface SyncScheduleRequest {
  repo_name: string;
  git_url: string;
  branch: string | null;
  interval_minutes: number;
  enabled: boolean;
}

export interface DeepSearchResponse {
  analysis?: string;
  business_flows?: Array<{
    name: string;
    impact?: string;
    [key: string]: unknown;
  }>;
  code_locations?: Array<{
    function?: string;
    file?: string;
    relevance?: string;
    [key: string]: unknown;
  }>;
  sufficient?: boolean;
  error?: boolean;
  search_trace?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}
