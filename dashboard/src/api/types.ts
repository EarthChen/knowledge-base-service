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

/** GET /stats/health — knowledge graph freshness and isolation signals */
export interface KnowledgeHealthStats {
  index_coverage: number;
  staleness_hours: number | null;
  orphan_ratio: number;
  last_indexed_at: string | null;
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
  offset: number;
  limit: number;
  query: string;
  entity_type?: string;
  confidence?: number;
  no_results_reason?: string;
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

/** Wiki-related fields exposed on GET /health (read-only server config). */
export interface WikiHealthConfig {
  cot_enabled: boolean;
  cot_analysis_model: string;
  cot_generation_model: string;
}

export interface HealthResponse {
  status: string;
  redis?: string;
  embedding?: string;
  wiki?: WikiHealthConfig;
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  file: string;
  line: number;
  end_line?: number | null;
  signature?: string;
  docstring?: string;
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

export interface GraphExpandRequest {
  node_name: string;
  center_uid?: string;
  limit?: number;
  depth?: number;
  exclude_uids?: string[];
}

export interface GraphExpandResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  center_uid: string;
}

export interface BlastRadiusNode {
  uid: string;
  name: string;
  type: string;
  file: string;
  relation: string;
  confidence: number;
}

export interface BlastRadiusResponse {
  center_entities: Array<{
    uid: string;
    name: string;
    type: string;
    file: string;
    line?: number | null;
  }>;
  affected: Array<{ depth: number; nodes: BlastRadiusNode[] }>;
  total_affected: number;
  summary: {
    by_type: Record<string, number>;
    by_relation: Record<string, number>;
    max_depth_reached: number;
  };
}

export interface CommunityMember {
  uid: string;
  name: string;
  type: string;
  file: string;
}

export interface CommunityInfo {
  id: number;
  label: string;
  size: number;
  members: CommunityMember[];
  cohesion: number;
}

export interface CommunitiesResponse {
  communities: CommunityInfo[];
  total_communities: number;
  unclustered_count: number;
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

export interface WebhookProviderConfig {
  secret: string;
}

export interface WebhookConfig {
  enabled: boolean;
  debounce_seconds: number;
  auto_update_branches: string[];
  providers: Record<string, WebhookProviderConfig>;
}

export interface AnalyzeImpactFile {
  path: string;
  status: "added" | "modified" | "removed" | "renamed";
}

export interface ImpactPage {
  wiki_page_path: string;
  impact_level: string;
  reason: string;
  affected_entities: string[];
}

export interface AnalyzeImpactResponse {
  affected_pages: ImpactPage[];
  summary: {
    high_impact: number;
    medium_impact: number;
    total_affected_pages: number;
  };
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

export interface ArchitectureMethod {
  uid: string;
  name: string;
  signature: string;
  fqn: string;
}

export interface ArchitectureClass {
  uid: string;
  name: string;
  fqn: string | null;
  file: string | null;
  repository: string | null;
  semantic_roles: string[] | null;
  architecture_layer: string;
  methods: ArchitectureMethod[];
}

export interface ArchitectureSearchResponse {
  layer: string;
  repository: string | null;
  limit: number;
  offset: number;
  classes: ArchitectureClass[];
  total: number;
  total_count: number;
}

/** POST /wiki/{repository}/lint */
export interface WikiLintIssue {
  severity: "error" | "warning" | "info";
  category: string;
  message: string;
  page_path?: string | null;
  entity_name?: string | null;
  suggestion?: string | null;
}

export interface WikiLintReport {
  issues: WikiLintIssue[];
  stats: {
    total: number;
    errors: number;
    warnings: number;
    info: number;
  };
  checked_at: string;
  scope: string;
}

/** GET /graph/insights/{repository} */
export type GraphInsightCategory =
  | "isolated"
  | "circular_dep"
  | "cross_layer"
  | "low_cohesion"
  | "bridge";

export interface GraphInsightItem {
  category: GraphInsightCategory;
  severity: "critical" | "warning" | "info";
  title: string;
  description: string;
  entities: string[];
  suggestion: string;
}

export interface GraphInsightsReport {
  insights: GraphInsightItem[];
  graph_stats: Record<string, number>;
  analyzed_at: string;
}

/** Wiki export preview / execute */
export type WikiExportAction = "create" | "update" | "skip";

export interface WikiExportDiff {
  file_path: string;
  action: WikiExportAction;
  wiki_content: string;
  repo_content: string | null;
  diff_summary: string;
}

export interface WikiExportResult {
  diffs: WikiExportDiff[];
  total_files: number;
  created: number;
  updated: number;
  skipped: number;
}
